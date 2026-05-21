import math
from typing import Optional
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from uuid import UUID
from datetime import datetime, timezone

from app.api.v1.deps import get_db, optional_jwt
from app.schemas.sessions import SessionCreate, SessionResponse, PaginatedSessionsResponse
from app.repositories.sessions_repository import SessionRepository
from app.repositories.profile_repository import ProfileRepository
from app.repositories.scenario_repository import ScenarioRepository
from app.repositories.users_repository import UsersRepository
from app.services.evaluation_service import run_auto_evaluation
from app.services.session_time_service import finalize_session_time

router = APIRouter(prefix="/sessions", tags=["sessions"])

_404 = {404: {"description": "Sesión no encontrada"}}
_400 = {400: {"description": "Solicitud inválida (p. ej. sesión ya cerrada)"}}


def _paginated_sessions(
    db: Session,
    payload: dict | None,
    view: str | None,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[int, list]:
    """Returns (total, items) respecting role and view filter."""
    if payload is None:
        return (
            SessionRepository.count_recent(db, status),
            SessionRepository.list_recent(db, limit, offset, status),
        )

    user_id = UUID(payload["sub"])
    user = UsersRepository.get_by_id(db, user_id)

    if not user or user.role in ("admin", "superadmin"):
        if view == "mine":
            return (
                SessionRepository.count_by_user(db, user_id, status),
                SessionRepository.list_by_user(db, user_id, limit, offset, status),
            )
        if view == "assigned":
            return (
                SessionRepository.count_assigned_to_others(db, user_id, user_id, status),
                SessionRepository.list_assigned_to_others(db, user_id, user_id, limit, offset, status),
            )
        return (
            SessionRepository.count_recent(db, status),
            SessionRepository.list_recent(db, limit, offset, status),
        )

    if user.role == "teacher":
        if view == "assigned":
            return (
                SessionRepository.count_assigned_to_others(db, user_id, user_id, status),
                SessionRepository.list_assigned_to_others(db, user_id, user_id, limit, offset, status),
            )
        return (
            SessionRepository.count_by_user(db, user_id, status),
            SessionRepository.list_by_user(db, user_id, limit, offset, status),
        )

    return (
        SessionRepository.count_by_user(db, user_id, status),
        SessionRepository.list_by_user(db, user_id, limit, offset, status),
    )


@router.get(
    "/",
    response_model=PaginatedSessionsResponse,
    summary="Listar sesiones (paginado)",
    description=(
        "Devuelve sesiones paginadas con filtrado por rol:\n\n"
        "- **Sin auth / admin**: todas las sesiones del sistema.\n"
        "- **teacher** (default / `view=mine`): sesiones propias. "
        "`view=assigned` devuelve sesiones asignadas a otros usuarios.\n"
        "- **student**: siempre solo sus propias sesiones.\n\n"
        "El parámetro `status` filtra por estado: `active`, `completed` o `terminated`."
    ),
    response_description="Página de sesiones con metadatos de paginación.",
)
def list_sessions(
    page: int = Query(1, ge=1, description="Número de página (base 1)."),
    limit: int = Query(20, ge=1, le=100, description="Máximo de ítems por página (1–100)."),
    view: Optional[str] = Query(None, description="Filtro de vista: `mine` o `assigned`."),
    status: Optional[str] = Query(None, description="Filtro por estado: `active`, `completed`, `terminated`."),
    db: Session = Depends(get_db),
    payload: dict | None = Depends(optional_jwt),
):
    offset = (page - 1) * limit
    total, items = _paginated_sessions(db, payload, view, status, limit, offset)
    pages = max(1, math.ceil(total / limit))
    return PaginatedSessionsResponse(items=items, total=total, page=page, pages=pages, limit=limit)




@router.post(
    "/start",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Iniciar sesión",
    description=(
        "Crea e inicia una nueva sesión vinculando un perfil de personaje simulado con un escenario. "
        "La severidad inicial se toma directamente del escenario. "
        "`user_id` y `assigned_by` se pueden omitir si hay JWT presente (se infieren del token)."
    ),
    response_description="Sesión creada en estado `active`.",
    responses={404: {"description": "Perfil o escenario no encontrado"}},
)
def start_session(
    payload_data: SessionCreate,
    db: Session = Depends(get_db),
    payload: dict | None = Depends(optional_jwt),
):
    profile = ProfileRepository.get_by_id(db, payload_data.profile_id)
    scenario = ScenarioRepository.get_by_id(db, payload_data.scenario_id)

    if not profile or not scenario:
        raise HTTPException(status_code=404, detail="Profile or Scenario not found")

    caller_id = UUID(payload["sub"]) if payload else None

    assigned_by = payload_data.assigned_by or caller_id
    user_id = payload_data.user_id or caller_id

    return SessionRepository.start(
        db, profile.id, scenario,
        profile=profile,
        user_id=user_id,
        assigned_by=assigned_by,
    )


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Obtener sesión por ID",
    description="Devuelve el detalle completo de una sesión, incluyendo severidad actual y tiempo acumulado.",
    response_description="Sesión encontrada.",
    responses=_404,
)
def get_session(
    session_id: UUID,
    db: Session = Depends(get_db),
):
    session = SessionRepository.get_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


class EndSessionBody(BaseModel):
    closing_kind: Optional[str] = Field(
        None,
        description=(
            "Motivo de cierre manual: "
            "`success` (resolución positiva), "
            "`crisis` (alta severidad), "
            "`inappropriate` (comportamiento inapropiado). "
            "Si se omite, la sesión se marca como `completed`."
        ),
        examples=["success"],
    )

    model_config = {
        "json_schema_extra": {"example": {"closing_kind": "success"}}
    }


class TimeFlushBody(BaseModel):
    delta_seconds: int = Field(
        ...,
        ge=0,
        le=600,
        description=(
            "Segundos de práctica transcurridos desde el último flush. "
            "Máximo 600 s (10 min) por llamada para evitar corrupción de datos."
        ),
        examples=[60],
    )

    model_config = {
        "json_schema_extra": {"example": {"delta_seconds": 60}}
    }


@router.patch(
    "/{session_id}/time",
    response_model=SessionResponse,
    summary="Reportar tiempo de práctica (PATCH)",
    description=(
        "Acumula el tiempo de práctica reportado por el frontend. "
        "Marca `time_source='explicit'` en el primer llamado. "
        "Ignorado silenciosamente si la sesión ya está cerrada. "
        "`delta_seconds` está limitado a 600 s por flush para prevenir datos inconsistentes.\n\n"
        "**Nota**: existe un alias `POST /{session_id}/time` porque `navigator.sendBeacon` "
        "solo soporta POST."
    ),
    response_description="Sesión con el tiempo acumulado actualizado.",
    responses=_404,
)
@router.post(
    "/{session_id}/time",
    response_model=SessionResponse,
    summary="Reportar tiempo de práctica (POST / sendBeacon)",
    description=(
        "Alias POST de `PATCH /{session_id}/time`. "
        "Necesario porque `navigator.sendBeacon` solo soporta POST. "
        "Comportamiento idéntico al PATCH."
    ),
    response_description="Sesión con el tiempo acumulado actualizado.",
    responses=_404,
    include_in_schema=False,
)
def flush_time(
    session_id: UUID,
    body: TimeFlushBody,
    db: Session = Depends(get_db),
):
    session = SessionRepository.add_time_delta(db, session_id, body.delta_seconds)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.patch(
    "/{session_id}/end",
    summary="Cerrar sesión",
    description=(
        "Finaliza una sesión activa. "
        "Registra `ended_at`, actualiza el `status` según el `closing_kind` y "
        "dispara el cálculo de métricas automáticas de evaluación.\n\n"
        "| `closing_kind` | `status` resultante |\n"
        "|---|---|\n"
        "| `success` o `null` | `completed` |\n"
        "| `crisis` | `terminated` |\n"
        "| `inappropriate` | `terminated` |"
    ),
    response_description="Confirmación de cierre con `session_id`, `ended_at` y `status`.",
    responses={**_404, **_400},
)
def end_session(
    session_id: UUID,
    body: EndSessionBody = Body(default=EndSessionBody()),
    db: Session = Depends(get_db),
):
    session = SessionRepository.get_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.ended_at:
        raise HTTPException(status_code=400, detail="Session already ended")

    session.ended_at = datetime.now(timezone.utc)
    session.status = 'terminated' if body.closing_kind in ('crisis', 'inappropriate') else 'completed'
    db.commit()

    try:
        finalize_session_time(db, session)
        db.commit()
    except Exception as exc:
        print(f"[sessions.end] finalize_session_time fallo: {type(exc).__name__}: {exc}")

    try:
        run_auto_evaluation(db, session.id)
    except Exception as exc:
        print(f"[sessions.end] run_auto_evaluation fallo: {type(exc).__name__}: {exc}")

    return {
        "message": "Session ended successfully",
        "session_id": session.id,
        "ended_at": session.ended_at,
        "status": session.status,
    }
