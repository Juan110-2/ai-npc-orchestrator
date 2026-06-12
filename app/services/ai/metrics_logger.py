"""
Capa que envuelve las llamadas a get_ai_client() y registra cada llamada
en ai_call_logs con metricas reales: latencia, tokens, validez de JSON,
costo estimado y estado de error.

Uso:
    with log_ai_call(db, purpose='classifier', session_id=sid) as log_ctx:
        ai = log_ctx.client
        ai_response = ai.generate_response(system_prompt, user_text)
        log_ctx.record_response(ai_response, json_valid=True)

El context manager garantiza que se persiste un log incluso si la llamada
truena (status='unknown_error' + error_detail).
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.pricing import estimate_cost_usd
from app.repositories.ai_call_logs_repository import AICallLogsRepository
from app.services.ai.base import AIClient, AIResponse, StreamResult
from app.services.ai.factory import get_ai_client

ALLOWED_PURPOSES = {"orchestrator", "classifier", "evaluator", "bench", "other"}
ALLOWED_STATUS = {
    "ok", "timeout", "parse_error", "safety_block",
    "rate_limit", "auth_error", "network_error", "unknown_error",
}

logger = logging.getLogger(__name__)


def _classify_exception(exc: BaseException) -> str:
    """Mapea una excepcion a uno de los status canonicos."""
    name = exc.__class__.__name__.lower()
    msg = str(exc).lower()
    if "timeout" in name or "timeout" in msg:
        return "timeout"
    if "rate" in msg or "ratelimit" in name or "429" in msg or "503" in msg or "unavailable" in msg or "high demand" in msg:
        return "rate_limit"
    if "auth" in name or "401" in msg or "unauthorized" in msg or "forbidden" in msg or "403" in msg:
        return "auth_error"
    if "safety" in msg or "blocked" in msg:
        return "safety_block"
    if "connection" in msg or "network" in msg:
        return "network_error"
    return "unknown_error"


@dataclass
class CallContext:
    """Estado mutable que el caller llena para que al cerrar el ctx se persista."""
    db: Session
    purpose: str
    provider_override: Optional[str] = None
    session_id: Optional[UUID] = None
    call_mode: str = "sync"

    client: AIClient = field(init=False)
    _start: float = field(init=False)
    prompt_chars: int = 0

    _status: str = "unknown_error"
    _error_detail: Optional[str] = None
    _tokens_input: Optional[int] = None
    _tokens_output: Optional[int] = None
    _latency_ms: Optional[float] = None
    _ttft_ms: Optional[float] = None
    _json_valid: Optional[bool] = None
    _response_chars: Optional[int] = None
    _category: Optional[str] = None

    def __post_init__(self) -> None:
        if self.purpose not in ALLOWED_PURPOSES:
            raise ValueError(f"purpose invalido: {self.purpose}")
        self.client = get_ai_client(self.provider_override)
        self._start = time.perf_counter()

    def record_prompt_chars(self, n: int) -> None:
        self.prompt_chars = max(0, int(n or 0))

    def record_response(
        self,
        ai_response: AIResponse,
        *,
        json_valid: Optional[bool] = None,
        category: Optional[str] = None,
    ) -> None:
        self._status = "ok"
        self._tokens_input = ai_response.tokens_input
        self._tokens_output = ai_response.tokens_output
        self._latency_ms = ai_response.latency_ms
        self._response_chars = len(ai_response.content or "")
        self._json_valid = json_valid
        self._category = category

    def record_stream_result(
        self,
        stream_result: StreamResult,
        accumulated_text: str,
        *,
        json_valid: Optional[bool] = None,
        category: Optional[str] = None,
    ) -> None:
        self._status = "ok"
        self._tokens_input = stream_result.tokens_input
        self._tokens_output = stream_result.tokens_output
        self._latency_ms = stream_result.latency_ms
        self._ttft_ms = stream_result.ttft_ms
        self._response_chars = len(accumulated_text or "")
        self._json_valid = json_valid
        self._category = category

    def record_error(self, exc: BaseException) -> None:
        self._status = _classify_exception(exc)
        self._error_detail = f"{exc.__class__.__name__}: {exc}"[:1000]

    def record_parse_error(self, raw_response: str) -> None:
        self._status = "parse_error"
        self._json_valid = False
        if raw_response:
            self._response_chars = len(raw_response)
            self._error_detail = f"json_parse_failed: {raw_response[:200]}"


@contextmanager
def log_ai_call(
    db: Session,
    *,
    purpose: str,
    session_id: Optional[UUID] = None,
    provider_override: Optional[str] = None,
    call_mode: str = "sync",
) -> Iterator[CallContext]:
    """
    Context manager que envuelve una llamada a IA. Persiste un AICallLog
    al cerrar el contexto, sea exito o fallo. Si el INSERT falla, escribe
    a stderr (no oculta el error) pero no tumba el flujo del usuario.
    """
    ctx = CallContext(
        db=db,
        purpose=purpose,
        provider_override=provider_override,
        session_id=session_id,
        call_mode=call_mode,
    )
    try:
        yield ctx
    except BaseException as exc:
        ctx.record_error(exc)
        # Persistir el log antes de relanzar
        _persist(ctx)
        raise
    else:
        _persist(ctx)


def _persist(ctx: CallContext) -> None:
    """Calcula costo y guarda el log. Si falla, lo registra sin romper el flujo."""
    if ctx._latency_ms is None:
        ctx._latency_ms = round((time.perf_counter() - ctx._start) * 1000, 2)

    cost_usd = None
    if ctx._tokens_input is not None and ctx._tokens_output is not None:
        cost_usd = estimate_cost_usd(
            ctx.client.provider,
            ctx.client.model,
            ctx._tokens_input,
            ctx._tokens_output,
        )

    try:
        AICallLogsRepository.add(
            db=ctx.db,
            provider=ctx.client.provider,
            model=ctx.client.model,
            purpose=ctx.purpose,
            call_mode=ctx.call_mode,
            status=ctx._status,
            error_detail=ctx._error_detail,
            category=ctx._category,
            session_id=ctx.session_id,
            tokens_input=ctx._tokens_input,
            tokens_output=ctx._tokens_output,
            latency_ms=ctx._latency_ms,
            ttft_ms=ctx._ttft_ms,
            json_valid=ctx._json_valid,
            response_chars=ctx._response_chars,
            prompt_chars=ctx.prompt_chars or None,
            cost_usd=cost_usd,
        )
    except Exception as log_exc:
        logger.exception(
            "[metrics_logger] ai_call_logs INSERT failed: %s: %s",
            type(log_exc).__name__,
            log_exc,
        )
        try:
            ctx.db.rollback()
        except Exception:
            pass
