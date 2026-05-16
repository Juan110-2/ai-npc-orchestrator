"""
Repositorio de ai_call_logs.
Usa INSERT crudo via SQLAlchemy text() para bypasear cualquier validacion
de metadata del ORM. Esto evita errores tipo NoReferencedTableError cuando
el script de bench no importa todos los modelos de la app.
"""
from uuid import UUID, uuid4
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.ai_call_log import AICallLog


_INSERT_SQL = text("""
    insert into public.ai_call_logs (
        id, session_id, provider, model, purpose, call_mode, status,
        category, error_detail, tokens_input, tokens_output, latency_ms, ttft_ms,
        json_valid, response_chars, prompt_chars, cost_usd
    ) values (
        :id, :session_id, :provider, :model, :purpose, :call_mode, :status,
        :category, :error_detail, :tokens_input, :tokens_output, :latency_ms, :ttft_ms,
        :json_valid, :response_chars, :prompt_chars, :cost_usd
    )
""")


class AICallLogsRepository:
    @staticmethod
    def add(
        db: Session,
        *,
        provider: str,
        model: str,
        purpose: str,
        status: str,
        category: Optional[str] = None,
        call_mode: str = "sync",
        session_id: Optional[UUID] = None,
        tokens_input: Optional[int] = None,
        tokens_output: Optional[int] = None,
        latency_ms: Optional[float] = None,
        ttft_ms: Optional[float] = None,
        json_valid: Optional[bool] = None,
        response_chars: Optional[int] = None,
        prompt_chars: Optional[int] = None,
        cost_usd: Optional[float] = None,
        error_detail: Optional[str] = None,
    ):
        new_id = uuid4()
        db.execute(
            _INSERT_SQL,
            {
                "id": new_id,
                "session_id": session_id,
                "provider": provider,
                "model": model,
                "purpose": purpose,
                "call_mode": call_mode,
                "status": status,
                "category": category,
                "error_detail": error_detail,
                "tokens_input": tokens_input,
                "tokens_output": tokens_output,
                "latency_ms": latency_ms,
                "ttft_ms": ttft_ms,
                "json_valid": json_valid,
                "response_chars": response_chars,
                "prompt_chars": prompt_chars,
                "cost_usd": cost_usd,
            },
        )
        db.commit()
        return new_id

    @staticmethod
    def list_by_provider(db: Session, provider: str, limit: int = 200):
        return (
            db.query(AICallLog)
            .filter(AICallLog.provider == provider)
            .order_by(AICallLog.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def list_recent(db: Session, limit: int = 500):
        return (
            db.query(AICallLog)
            .order_by(AICallLog.created_at.desc())
            .limit(limit)
            .all()
        )
