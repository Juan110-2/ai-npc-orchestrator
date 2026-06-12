import logging
import math
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, optional_jwt
from app.models.ai_call_log import AICallLog
from app.repositories.profile_repository import ProfileRepository
from app.repositories.scenario_repository import ScenarioRepository
from app.repositories.sessions_repository import SessionRepository
from app.repositories.users_repository import UsersRepository
from app.schemas.sessions import PaginatedSessionsResponse, SessionCreate, SessionResponse
from app.services.evaluation.service import run_auto_evaluation
from app.services.sessions.time_service import finalize_session_time

logger = logging.getLogger(__name__)


def _commit_session_update(db: Session, session_id: UUID, *, source: str) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("[%s] Falló commit para session_id=%s", source, session_id)
        raise


def _run_post_close_hooks(db: Session, session) -> None:
    """Ejecuta pasos posteriores al cierre sin ocultar trazabilidad operativa."""
    try:
        finalize_session_time(db, session)
        _commit_session_update(db, session.id, source="sessions.end.finalize_time")
    except Exception:
        logger.exception(
            "[sessions.end] Falló finalize_session_time para session_id=%s",
            session.id,
        )

    try:
        run_auto_evaluation(db, session.id)
    except Exception:
        db.rollback()
        logger.exception(
            "[sessions.end] Falló run_auto_evaluation para session_id=%s",
            session.id,
        )


def _resolve_session_actor(db: Session, payload: dict | None):
    if payload is None:
        return None, None
    user_id = UUID(payload["sub"])
    user = UsersRepository.get_by_id(db, user_id)
    return user_id, user


def _list_all_sessions(db: Session, limit: int, offset: int, status_filter: str | None) -> tuple[int, list]:
    return (
        SessionRepository.count_recent(db, status_filter),
        SessionRepository.list_recent(db, limit, offset, status_filter),
    )


def _list_user_sessions(
    db: Session,
    user_id: UUID,
    limit: int,
    offset: int,
    status_filter: str | None,
) -> tuple[int, list]:
    return (
        SessionRepository.count_by_user(db, user_id, status_filter),
        SessionRepository.list_by_user(db, user_id, limit, offset, status_filter),
    )


def _list_assigned_sessions(
    db: Session,
    user_id: UUID,
    limit: int,
    offset: int,
    status_filter: str | None,
) -> tuple[int, list]:
    return (
        SessionRepository.count_assigned_to_others(db, user_id, user_id, status_filter),
        SessionRepository.list_assigned_to_others(db, user_id, user_id, limit, offset, status_filter),
    )


def _last_model_map(db: Session, session_ids: list) -> dict[str, str]:
    """Batch query: retorna `{session_id: model}` para la llamada `ok` más reciente."""
    if not session_ids:
        return {}
    latest = (
        db.query(
            AICallLog.session_id,
            func.max(AICallLog.created_at).label("max_ts"),
        )
        .filter(AICallLog.session_id.in_(session_ids), AICallLog.status == "ok")
        .group_by(AICallLog.session_id)
        .subquery()
    )
    rows = (
        db.query(AICallLog.session_id, AICallLog.model)
        .join(
            latest,
            (AICallLog.session_id == latest.c.session_id)
            & (AICallLog.created_at == latest.c.max_ts),
        )
        .all()
    )
    return {str(r.session_id): r.model for r in rows}


router = APIRouter(prefix="/sessions", tags=["sessions"])

_404 = {404: {"description": "Sesión no encontrada"}}
_400 = {400: {"description": "Solicitud inválida, por ejemplo una sesión ya cerrada"}}


def _paginated_sessions(
    db: Session,
    payload: dict | None,
    view: str | None,
    status_filter: str | None,
    limit: int,
    offset: int,
) -> tuple[int, list]:
    """Retorna `(total, items)` respetando rol y filtro de vista."""
    if payload is None:
        return _list_all_sessions(db, limit, offset, status_filter)

    user_id, user = _resolve_session_actor(db, payload)

    if not user or user.role in ("admin", "superadmin"):
        if view == "mine":
            return _list_user_sessions(db, user_id, limit, offset, status_filter)
        if view == "assigned":
            return _list_assigned_sessions(db, user_id, limit, offset, status_filter)
        return _list_all_sessions(db, limit, offset, status_filter)

    if user.role == "teacher":
        if view == "assigned":
            return _list_assigned_sessions(db, user_id, limit, offset, status_filter)
        return _list_user_sessions(db, user_id, limit, offset, status_filter)

    return _list_user_sessions(db, user_id, limit, offset, status_filter)


def _resolve_start_session_actor(payload: dict | None) -> UUID | None:
    return UUID(payload["sub"]) if payload else None


def _apply_manual_session_close(session, closing_kind: str | None) -> None:
    session.ended_at = datetime.now(timezone.utc)
    session.status = "terminated" if closing_kind in ("crisis", "inappropriate") else "completed"


class EndSessionBody(BaseModel):
    closing_kind: Optional[str] = Field(
        None,
        description=(
            "Motivo de cierre manual: `success`, `crisis` o `inappropriate`. "
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
            "Máximo 600 segundos por llamada para evitar datos inconsistentes."
        ),
        examples=[60],
    )

    model_config = {
        "json_schema_extra": {"example": {"delta_seconds": 60}}
    }


class EndSessionResponse(BaseModel):
    message: str = Field(..., description="Mensaje corto de confirmación.")
    session_id: UUID = Field(..., description="UUID de la sesión cerrada.")
    ended_at: datetime = Field(..., description="Fecha y hora efectiva de cierre (UTC).")
    status: str = Field(..., description="Estado final de la sesión tras el cierre.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "message": "Session ended successfully",
                "session_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
                "ended_at": "2025-05-10T09:30:00Z",
                "status": "completed",
            }
        }
    }


@router.get(
    "/",
    response_model=PaginatedSessionsResponse,
    summary="Listar sesiones",
    description=(
        "Devuelve sesiones paginadas con filtrado por rol:\n\n"
        "- Sin auth o `admin`: todas las sesiones.\n"
        "- `teacher`: por defecto sus propias sesiones; `view=assigned` devuelve sesiones asignadas a otros usuarios.\n"
        "- `student`: siempre solo sus propias sesiones.\n\n"
        "El parámetro `status` filtra por estado: `active`, `completed` o `terminated`."
    ),
    response_description="Página de sesiones con metadatos de paginación.",
)
def list_sessions(
    page: int = Query(1, ge=1, description="Número de página, base 1."),
    limit: int = Query(20, ge=1, le=100, description="Cantidad máxima de ítems por página."),
    view: Optional[str] = Query(None, description="Filtro de vista: `mine` o `assigned`."),
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        description="Filtro por estado: `active`, `completed` o `terminated`.",
    ),
    db: Session = Depends(get_db),
    payload: dict | None = Depends(optional_jwt),
):
    offset = (page - 1) * limit
    total, items = _paginated_sessions(db, payload, view, status_filter, limit, offset)
    pages = max(1, math.ceil(total / limit))
    model_map = _last_model_map(db, [s.id for s in items])
    session_items = [
        SessionResponse.model_validate(s).model_copy(update={"last_ai_model": model_map.get(str(s.id))})
        for s in items
    ]
    return PaginatedSessionsResponse(items=session_items, total=total, page=page, pages=pages, limit=limit)


@router.post(
    "/start",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Iniciar sesión",
    description=(
        "Crea e inicia una nueva sesión vinculando un perfil de personaje simulado con un escenario. "
        "La severidad inicial se toma directamente del escenario.\n\n"
        "Si existe JWT, `user_id` y `assigned_by` pueden omitirse y se infieren automáticamente "
        "desde el token."
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

    caller_id = _resolve_start_session_actor(payload)
    assigned_by = payload_data.assigned_by or caller_id
    user_id = payload_data.user_id or caller_id

    return SessionRepository.start(
        db,
        profile.id,
        scenario,
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


@router.patch(
    "/{session_id}/time",
    response_model=SessionResponse,
    summary="Reportar tiempo de práctica",
    description=(
        "Acumula tiempo de práctica reportado por el frontend. "
        "Marca `time_source='explicit'` en el primer llamado. "
        "Si la sesión ya está cerrada, la operación se ignora silenciosamente.\n\n"
        "`delta_seconds` está limitado a 600 segundos por flush para prevenir datos inconsistentes."
    ),
    response_description="Sesión con el tiempo acumulado actualizado.",
    responses=_404,
)
@router.post(
    "/{session_id}/time",
    response_model=SessionResponse,
    summary="Alias POST para reportar tiempo",
    description=(
        "Alias de `PATCH /{session_id}/time`, útil para integraciones que solo soportan POST, "
        "como `navigator.sendBeacon`."
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
    response_model=EndSessionResponse,
    summary="Cerrar sesión",
    description=(
        "Finaliza una sesión activa. "
        "Registra `ended_at`, actualiza el `status` según el `closing_kind` y dispara "
        "el cálculo de métricas automáticas de evaluación.\n\n"
        "- `success` o `null` -> `completed`\n"
        "- `crisis` -> `terminated`\n"
        "- `inappropriate` -> `terminated`"
    ),
    response_description="Confirmación de cierre con estado final.",
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

    _apply_manual_session_close(session, body.closing_kind)
    _commit_session_update(db, session.id, source="sessions.end")
    _run_post_close_hooks(db, session)

    return {
        "message": "Session ended successfully",
        "session_id": session.id,
        "ended_at": session.ended_at,
        "status": session.status,
    }
