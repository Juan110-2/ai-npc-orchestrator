import math
from typing import Optional
from fastapi import APIRouter, Body, Depends, HTTPException, Query
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
        # view=mine or default: sessions where teacher is the trainee
        return (
            SessionRepository.count_by_user(db, user_id, status),
            SessionRepository.list_by_user(db, user_id, limit, offset, status),
        )

    # student: always their own sessions
    return (
        SessionRepository.count_by_user(db, user_id, status),
        SessionRepository.list_by_user(db, user_id, limit, offset, status),
    )


@router.get("/", response_model=PaginatedSessionsResponse)
def list_sessions(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    view: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    payload: dict | None = Depends(optional_jwt),
):
    offset = (page - 1) * limit
    total, items = _paginated_sessions(db, payload, view, status, limit, offset)
    pages = max(1, math.ceil(total / limit))
    return PaginatedSessionsResponse(items=items, total=total, page=page, pages=pages, limit=limit)


@router.get("/list", response_model=PaginatedSessionsResponse)
def list_sessions_explicit(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    view: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    payload: dict | None = Depends(optional_jwt),
):
    offset = (page - 1) * limit
    total, items = _paginated_sessions(db, payload, view, status, limit, offset)
    pages = max(1, math.ceil(total / limit))
    return PaginatedSessionsResponse(items=items, total=total, page=page, pages=pages, limit=limit)


@router.get("/active", response_model=list[SessionResponse])
def list_active_sessions(
    db: Session = Depends(get_db),
    payload: dict | None = Depends(optional_jwt),
):
    if payload is None:
        sessions = SessionRepository.list_recent(db, limit=100)
    else:
        user_id = UUID(payload["sub"])
        user = UsersRepository.get_by_id(db, user_id)
        if not user or user.role in ("admin", "superadmin"):
            sessions = SessionRepository.list_recent(db, limit=100)
        elif user.role == "teacher":
            sessions = SessionRepository.list_by_assigned_by(db, user_id, limit=100)
        else:
            sessions = SessionRepository.list_by_user(db, user_id, limit=100)
    return [s for s in sessions if not s.ended_at]


@router.post("/start", response_model=SessionResponse)
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


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: UUID, db: Session = Depends(get_db)):
    session = SessionRepository.get_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


class EndSessionBody(BaseModel):
    closing_kind: Optional[str] = None  # 'success' | 'crisis' | 'inappropriate' | None


class TimeFlushBody(BaseModel):
    delta_seconds: int = Field(..., ge=0, le=600)


@router.patch("/{session_id}/time", response_model=SessionResponse)
def flush_time(
    session_id: UUID,
    body: TimeFlushBody,
    db: Session = Depends(get_db),
):
    """
    Accumulate practice time reported by an instrumented frontend.
    Marks time_source='explicit' on first call.
    Ignored silently if the session is already closed.
    delta_seconds capped at 600 (10 min) per flush to prevent corruption.
    """
    session = SessionRepository.add_time_delta(db, session_id, body.delta_seconds)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.patch("/{session_id}/end")
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
