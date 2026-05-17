from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from datetime import datetime, timezone

from app.api.v1.deps import get_db, optional_jwt
from app.schemas.sessions import SessionCreate, SessionResponse
from app.repositories.sessions_repository import SessionRepository
from app.repositories.profile_repository import ProfileRepository
from app.repositories.scenario_repository import ScenarioRepository
from app.repositories.users_repository import UsersRepository
from app.services.evaluation_service import run_auto_evaluation

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _list_sessions_for_caller(db: Session, payload: dict | None, limit: int = 50):
    """Filtra sesiones según el rol del caller."""
    if payload is None:
        return SessionRepository.list_recent(db, limit=limit)

    user_id = UUID(payload["sub"])
    user = UsersRepository.get_by_id(db, user_id)

    if not user or user.role == "admin":
        return SessionRepository.list_recent(db, limit=limit)
    if user.role == "teacher":
        return SessionRepository.list_by_assigned_by(db, user_id, limit=limit)
    # student
    return SessionRepository.list_by_user(db, user_id, limit=limit)


@router.get("/", response_model=list[SessionResponse])
def list_sessions(
    db: Session = Depends(get_db),
    payload: dict | None = Depends(optional_jwt),
):
    return _list_sessions_for_caller(db, payload)


@router.get("/list", response_model=list[SessionResponse])
def list_sessions_explicit(
    db: Session = Depends(get_db),
    payload: dict | None = Depends(optional_jwt),
):
    return _list_sessions_for_caller(db, payload)


@router.get("/active", response_model=list[SessionResponse])
def list_active_sessions(
    db: Session = Depends(get_db),
    payload: dict | None = Depends(optional_jwt),
):
    sessions = _list_sessions_for_caller(db, payload, limit=100)
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


@router.patch("/{session_id}/end")
def end_session(
    session_id: UUID,
    db: Session = Depends(get_db),
):
    """
    Finaliza una sesion de practica clinica y dispara el calculo
    automatico de las metricas pedagogicas (session_evaluations).
    """
    session = SessionRepository.get_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.ended_at:
        raise HTTPException(status_code=400, detail="Session already ended")

    session.ended_at = datetime.now(timezone.utc)
    db.commit()

    try:
        run_auto_evaluation(db, session.id)
    except Exception as exc:
        print(f"[sessions.end] run_auto_evaluation fallo: {type(exc).__name__}: {exc}")

    return {
        "message": "Session ended successfully",
        "session_id": session.id,
        "ended_at": session.ended_at,
    }