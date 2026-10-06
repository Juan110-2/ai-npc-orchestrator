"""
Endpoints de métricas técnicas para selección y comparación de proveedores de IA.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, resolve_authenticated_user
from app.models.ai_call_log import AICallLog
from app.models.user_profile import UserProfile

router = APIRouter(prefix="/admin/metrics", tags=["admin-metrics"])
logger = logging.getLogger(__name__)

_security = HTTPBearer(auto_error=False)


class ProviderMetricsRow(BaseModel):
    provider: str
    model: str
    purpose: str
    n_calls: int | None = None
    n_ok: int | None = None
    n_errors: int | None = None
    success_rate_pct: float | None = None
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    p99_latency_ms: float | None = None
    mean_latency_ms: float | None = None
    mean_ttft_ms: float | None = None
    p95_ttft_ms: float | None = None
    mean_tokens_input: float | None = None
    mean_tokens_output: float | None = None
    total_tokens_input: int | None = None
    total_tokens_output: int | None = None
    json_valid_rate_pct: float | None = None
    total_cost_usd: float | None = None
    mean_cost_usd_per_call: float | None = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "purpose": "orchestrator",
                "n_calls": 120,
                "n_ok": 118,
                "n_errors": 2,
                "success_rate_pct": 98.3,
                "p50_latency_ms": 740.0,
                "p95_latency_ms": 1320.0,
                "p99_latency_ms": 1800.0,
                "mean_latency_ms": 802.0,
                "mean_ttft_ms": 310.0,
                "p95_ttft_ms": 540.0,
                "mean_tokens_input": 420.5,
                "mean_tokens_output": 155.2,
                "total_tokens_input": 50460,
                "total_tokens_output": 18624,
                "json_valid_rate_pct": 100.0,
                "total_cost_usd": 2.3145,
                "mean_cost_usd_per_call": 0.0193,
            }
        }
    }


class RecentCallItem(BaseModel):
    id: str
    session_id: str | None = None
    provider: str | None = None
    model: str | None = None
    purpose: str | None = None
    call_mode: str | None = None
    status: str | None = None
    category: str | None = None
    tokens_input: int | None = None
    tokens_output: int | None = None
    latency_ms: float | None = None
    ttft_ms: float | None = None
    json_valid: bool | None = None
    response_chars: int | None = None
    prompt_chars: int | None = None
    cost_usd: float | None = None
    error_detail: str | None = None
    created_at: str | None = None


class RecentCallsResponse(BaseModel):
    items: list[RecentCallItem]
    total: int
    limit: int
    offset: int

    model_config = {
        "json_schema_extra": {
            "example": {
                "items": [
                    {
                        "id": "1f2e3d4c-5b6a-7980-1234-abcdef123456",
                        "session_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "purpose": "orchestrator",
                        "call_mode": "sync",
                        "status": "ok",
                        "category": "conversation",
                        "tokens_input": 420,
                        "tokens_output": 160,
                        "latency_ms": 812.0,
                        "ttft_ms": 295.0,
                        "json_valid": True,
                        "response_chars": 248,
                        "prompt_chars": 1530,
                        "cost_usd": 0.0184,
                        "error_detail": None,
                        "created_at": "2025-05-10T09:01:45+00:00",
                    }
                ],
                "total": 1,
                "limit": 15,
                "offset": 0,
            }
        }
    }


class MetricsTotals(BaseModel):
    total_calls: int
    total_ok: int
    total_errors: int
    total_tokens_in: int
    total_tokens_out: int
    total_cost_usd: float
    n_providers: int
    n_sessions: int


class MetricsByProvider(BaseModel):
    provider: str
    model: str
    n_calls: int
    n_ok: int | None = None
    success_rate_pct: float | None = None
    mean_latency_ms: float | None = None
    cost_usd: float | None = None


class MetricsByPurpose(BaseModel):
    purpose: str
    n_calls: int
    mean_latency_ms: float | None = None
    json_valid_rate_pct: float | None = None


class MetricsSummaryResponse(BaseModel):
    totals: MetricsTotals
    by_provider: list[MetricsByProvider]
    by_purpose: list[MetricsByPurpose]

    model_config = {
        "json_schema_extra": {
            "example": {
                "totals": {
                    "total_calls": 240,
                    "total_ok": 235,
                    "total_errors": 5,
                    "total_tokens_in": 102400,
                    "total_tokens_out": 36800,
                    "total_cost_usd": 4.8123,
                    "n_providers": 3,
                    "n_sessions": 18,
                },
                "by_provider": [
                    {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "n_calls": 120,
                        "n_ok": 118,
                        "success_rate_pct": 98.3,
                        "mean_latency_ms": 802.0,
                        "cost_usd": 2.3145,
                    }
                ],
                "by_purpose": [
                    {
                        "purpose": "orchestrator",
                        "n_calls": 160,
                        "mean_latency_ms": 845.0,
                        "json_valid_rate_pct": 100.0,
                    }
                ],
            }
        }
    }


def _require_admin(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> UserProfile:
    user = resolve_authenticated_user(db=db, credentials=credentials)

    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo administradores pueden ver las métricas técnicas",
        )
    return user


@router.get(
    "/providers",
    response_model=list[ProviderMetricsRow],
    summary="Ver métricas por proveedor",
    description=(
        "Devuelve métricas agregadas por proveedor, modelo y propósito de llamada "
        "a partir de la vista `public.v_provider_metrics`."
    ),
    response_description="Lista de métricas agrupadas por proveedor, modelo y propósito.",
    responses={
        401: {"description": "Token no enviado o inválido"},
        403: {"description": "Se requiere rol `admin`"},
    },
)
def get_provider_metrics(
    db: Session = Depends(get_db),
    purpose: Optional[str] = Query(
        default=None,
        description="Filtrar por propósito: `orchestrator`, `classifier` o `evaluator`.",
    ),
    _: Optional[UserProfile] = Depends(_require_admin),
):
    where_clause = ""
    params: dict = {}
    if purpose:
        where_clause = "where purpose = :purpose"
        params["purpose"] = purpose

    sql = text(f"""
        select
            provider, model, purpose,
            n_calls, n_ok, n_errors,
            success_rate_pct,
            p50_latency_ms, p95_latency_ms, p99_latency_ms, mean_latency_ms,
            mean_ttft_ms, p95_ttft_ms,
            mean_tokens_input, mean_tokens_output,
            total_tokens_input, total_tokens_output,
            json_valid_rate_pct,
            total_cost_usd, mean_cost_usd_per_call
        from public.v_provider_metrics
        {where_clause}
        order by provider, model, purpose
    """)
    rows = db.execute(sql, params).mappings().all()
    return [dict(r) for r in rows]


@router.get(
    "/calls",
    response_model=RecentCallsResponse,
    summary="Listar llamadas recientes a IA",
    description=(
        "Devuelve el log más reciente de llamadas a proveedores de IA, con filtros por proveedor, "
        "propósito y `session_id`, además de paginación por `limit` y `offset`."
    ),
    response_description="Lista paginada de llamadas recientes a IA.",
    responses={
        401: {"description": "Token no enviado o inválido"},
        403: {"description": "Se requiere rol `admin`"},
    },
)
def list_recent_calls(
    db: Session = Depends(get_db),
    limit: int = Query(default=15, ge=1, le=100, description="Cantidad máxima de registros a devolver."),
    offset: int = Query(default=0, ge=0, description="Desplazamiento inicial para la paginación."),
    provider: Optional[str] = Query(default=None, description="Filtrar por proveedor."),
    purpose: Optional[str] = Query(default=None, description="Filtrar por propósito de llamada."),
    session_id: Optional[str] = Query(
        default=None,
        description="Filtrar por `session_id` completo o por prefijo.",
    ),
    _: Optional[UserProfile] = Depends(_require_admin),
):
    from sqlalchemy import Text, cast

    q = db.query(AICallLog)
    if provider:
        q = q.filter(AICallLog.provider == provider)
    if purpose:
        q = q.filter(AICallLog.purpose == purpose)
    if session_id:
        q = q.filter(cast(AICallLog.session_id, Text).ilike(f"{session_id.strip()}%"))
    total = q.count()
    rows = q.order_by(AICallLog.created_at.desc()).offset(offset).limit(limit).all()
    items = [
        {
            "id": str(r.id),
            "session_id": str(r.session_id) if r.session_id else None,
            "provider": r.provider,
            "model": r.model,
            "purpose": r.purpose,
            "call_mode": r.call_mode,
            "status": r.status,
            "category": r.category,
            "tokens_input": r.tokens_input,
            "tokens_output": r.tokens_output,
            "latency_ms": r.latency_ms,
            "ttft_ms": r.ttft_ms,
            "json_valid": r.json_valid,
            "response_chars": r.response_chars,
            "prompt_chars": r.prompt_chars,
            "cost_usd": r.cost_usd,
            "error_detail": r.error_detail,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get(
    "/summary",
    response_model=MetricsSummaryResponse,
    summary="Obtener resumen global de métricas",
    description=(
        "Devuelve un resumen consolidado de las llamadas a IA en tres niveles: `totals`, "
        "`by_provider` y `by_purpose`."
    ),
    response_description="Objeto con resumen global, por proveedor y por propósito.",
    responses={
        401: {"description": "Token no enviado o inválido"},
        403: {"description": "Se requiere rol `admin`"},
    },
)
def get_metrics_summary(
    db: Session = Depends(get_db),
    _: Optional[UserProfile] = Depends(_require_admin),
):
    totals = db.execute(text("""
        select
            count(*)::int                                          as total_calls,
            count(*) filter (where status='ok')::int               as total_ok,
            count(*) filter (where status<>'ok')::int              as total_errors,
            coalesce(sum(tokens_input), 0)::bigint                 as total_tokens_in,
            coalesce(sum(tokens_output), 0)::bigint                as total_tokens_out,
            coalesce(round(sum(cost_usd)::numeric, 6), 0)          as total_cost_usd,
            count(distinct provider)::int                          as n_providers,
            count(distinct session_id) filter (where session_id is not null)::int
                                                                   as n_sessions
        from public.ai_call_logs
    """)).mappings().one()

    by_provider = db.execute(text("""
        select
            provider, model,
            count(*)::int                                   as n_calls,
            count(*) filter (where status='ok')::int        as n_ok,
            round(100.0 * count(*) filter (where status='ok') / nullif(count(*),0), 1)
                                                            as success_rate_pct,
            round(avg(latency_ms) filter (where status='ok')::numeric, 0)
                                                            as mean_latency_ms,
            round(sum(cost_usd) filter (where status='ok')::numeric, 6)
                                                            as cost_usd
        from public.ai_call_logs
        group by provider, model
        order by provider, model
    """)).mappings().all()

    by_purpose = db.execute(text("""
        select
            purpose,
            count(*)::int as n_calls,
            round(avg(latency_ms) filter (where status='ok')::numeric, 0)
                          as mean_latency_ms,
            round(100.0 * count(*) filter (where json_valid=true) /
                  nullif(count(*) filter (where purpose in ('classifier','evaluator')), 0), 1)
                          as json_valid_rate_pct
        from public.ai_call_logs
        group by purpose
        order by purpose
    """)).mappings().all()

    return {
        "totals": dict(totals),
        "by_provider": [dict(r) for r in by_provider],
        "by_purpose": [dict(r) for r in by_purpose],
    }
