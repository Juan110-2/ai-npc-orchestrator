"""
Endpoints de metricas tecnicas para seleccion de API de IA (Capitulo 3 del TG).

Permisos:
    - admin: lectura total.
    - teacher: 403 forbidden.
    - student: 403 forbidden.
    - sin auth (modo dev, SUPABASE_JWT_SECRET no configurado): lectura total.
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db
from app.core.config import SUPABASE_JWT_SECRET
from app.models.user_profile import UserProfile
from app.repositories.ai_call_logs_repository import AICallLogsRepository
from app.repositories.users_repository import UsersRepository

router = APIRouter(prefix="/admin/metrics", tags=["admin-metrics"])

_security = HTTPBearer(auto_error=False)


def _require_admin(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> Optional[UserProfile]:
    """Solo admin. Modo dev (sin SUPABASE_JWT_SECRET) pasa."""
    if not SUPABASE_JWT_SECRET:
        return None

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization Bearer requerido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        from jose import jwt
        token = credentials.credentials
        unverified = jwt.get_unverified_claims(token)
        user_id_str = unverified.get("sub")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sin claim 'sub'",
        )

    try:
        user = UsersRepository.get_by_id(db, UUID(user_id_str))
    except Exception:
        user = None

    if not user or user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo administradores pueden ver las metricas tecnicas",
        )
    return user


@router.get(
    "/providers",
    summary="Métricas por proveedor 🔒 admin",
    description=(
        "Devuelve métricas agregadas de rendimiento por proveedor de IA, modelo y propósito "
        "(leídas desde la vista `v_provider_metrics` en PostgreSQL).\n\n"
        "**Campos retornados por fila:**\n\n"
        "| Campo | Descripción |\n"
        "|---|---|\n"
        "| `provider` / `model` / `purpose` | Identificadores |\n"
        "| `n_calls`, `n_ok`, `n_errors` | Conteos |\n"
        "| `success_rate_pct` | Tasa de éxito (%) |\n"
        "| `p50_latency_ms`, `p95_latency_ms`, `p99_latency_ms`, `mean_latency_ms` | Latencia |\n"
        "| `mean_ttft_ms`, `p95_ttft_ms` | Tiempo al primer token |\n"
        "| `total_cost_usd`, `mean_cost_usd_per_call` | Costo |\n"
        "| `json_valid_rate_pct` | Tasa de respuestas JSON válidas |\n\n"
        "El parámetro opcional `purpose` filtra por propósito: `orchestrator`, `classifier`, `evaluator`."
    ),
    response_description="Lista de filas de métricas agrupadas por proveedor, modelo y propósito.",
    responses={
        401: {"description": "Token no enviado o inválido"},
        403: {"description": "Se requiere rol `admin`"},
    },
)
def get_provider_metrics(
    db: Session = Depends(get_db),
    purpose: Optional[str] = Query(
        default=None,
        description="Filtrar por propósito de llamada: `orchestrator`, `classifier`, `evaluator`.",
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
    summary="Últimas llamadas a IA 🔒 admin",
    description=(
        "Devuelve el log de las llamadas más recientes a los proveedores de IA, "
        "con detalles de tokens, latencia, costo y estado.\n\n"
        "Filtros disponibles:\n"
        "- `limit`: número de registros a devolver (1–1000, default 100).\n"
        "- `provider`: filtra por proveedor específico (p. ej. `openai`, `gemini`, `deepseek`)."
    ),
    response_description="Lista de registros de llamadas ordenados por fecha descendente.",
    responses={
        401: {"description": "Token no enviado o inválido"},
        403: {"description": "Se requiere rol `admin`"},
    },
)
def list_recent_calls(
    db: Session = Depends(get_db),
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
        description="Número de registros a devolver (1–1000).",
    ),
    provider: Optional[str] = Query(
        default=None,
        description="Filtrar por proveedor: `openai`, `gemini`, `deepseek`, etc.",
    ),
    _: Optional[UserProfile] = Depends(_require_admin),
):
    rows = (
        AICallLogsRepository.list_by_provider(db, provider, limit=limit)
        if provider else AICallLogsRepository.list_recent(db, limit=limit)
    )
    return [
        {
            "id": str(r.id),
            "session_id": str(r.session_id) if r.session_id else None,
            "provider": r.provider, "model": r.model,
            "purpose": r.purpose, "call_mode": r.call_mode,
            "status": r.status,
            "tokens_input": r.tokens_input, "tokens_output": r.tokens_output,
            "latency_ms": r.latency_ms, "ttft_ms": r.ttft_ms,
            "json_valid": r.json_valid,
            "response_chars": r.response_chars, "prompt_chars": r.prompt_chars,
            "cost_usd": r.cost_usd, "error_detail": r.error_detail,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get(
    "/summary",
    summary="Resumen global de métricas 🔒 admin",
    description=(
        "Devuelve un resumen consolidado de todas las llamadas a IA, estructurado en tres niveles:\n\n"
        "- **`totals`**: totales globales (llamadas, tokens, errores, costo, proveedores únicos).\n"
        "- **`by_provider`**: desglose por proveedor y modelo (llamadas, tasa de éxito, "
        "latencia media, costo).\n"
        "- **`by_purpose`**: desglose por propósito de llamada (`orchestrator`, `classifier`, "
        "`evaluator`), con latencia media y tasa de JSON válido."
    ),
    response_description=(
        "Objeto con `totals` (dict), `by_provider` (lista) y `by_purpose` (lista)."
    ),
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
