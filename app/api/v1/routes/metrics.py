"""
Endpoints de métricas técnicas para selección y comparación de proveedores de IA.

Acceso:
  - `admin`: lectura total.
  - `teacher` y `student`: sin acceso.
  - sin auth (modo dev): lectura total si `SUPABASE_JWT_SECRET` no está configurado.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, resolve_authenticated_user
from app.core.config import SUPABASE_JWT_SECRET
from app.models.ai_call_log import AICallLog
from app.models.user_profile import UserProfile

router = APIRouter(prefix="/admin/metrics", tags=["admin-metrics"])
logger = logging.getLogger(__name__)

_security = HTTPBearer(auto_error=False)


def _require_admin(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> Optional[UserProfile]:
    """Permite acceso solo a usuarios con rol `admin`."""
    if not SUPABASE_JWT_SECRET:
        return None

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization Bearer requerido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = resolve_authenticated_user(
        db=db,
        credentials=credentials,
        allow_missing_credentials=False,
    )
    if user is None:
        logger.warning("[metrics] Se esperaba usuario autenticado pero no se resolvió perfil")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario autenticado sin perfil asociado",
        )

    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo administradores pueden ver las métricas técnicas",
        )
    return user


@router.get(
    "/providers",
    summary="Ver métricas por proveedor",
    description=(
        "Devuelve métricas agregadas de rendimiento por proveedor, modelo y propósito de llamada, "
        "a partir de la vista `public.v_provider_metrics`.\n\n"
        "Incluye conteos, tasas de éxito, latencias, uso de tokens, tiempo al primer token, "
        "validez de JSON y costo. Puede filtrarse por `purpose`."
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
    summary="Listar llamadas recientes a IA",
    description=(
        "Devuelve el log más reciente de llamadas a proveedores de IA, incluyendo "
        "estado, modelo, propósito, tokens, latencia, costo y errores.\n\n"
        "Soporta filtros por proveedor, propósito y `session_id`, además de paginación "
        "basada en `limit` y `offset`."
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
    summary="Obtener resumen global de métricas",
    description=(
        "Devuelve un resumen consolidado de las llamadas a IA en tres niveles:\n\n"
        "- `totals`: conteos globales, tokens, costo y cantidad de proveedores/sesiones.\n"
        "- `by_provider`: desglose por proveedor y modelo.\n"
        "- `by_purpose`: desglose por propósito (`orchestrator`, `classifier`, `evaluator`)."
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
