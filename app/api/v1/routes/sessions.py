from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from datetime import datetime

from app.api.v1.deps import get_db
from app.schemas.sessions import SessionCreate, SessionResponse
from app.repositories.sessions_repository import SessionRepository
from app.repositories.profile_repository import ProfileRepository
from app.repositories.scenario_repository import ScenarioRepository

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("/", response_model=list[SessionResponse])
def list_sessions(db: Session = Depends(get_db)):
    return SessionRepository.list_recent(db, limit=50)


@router.get("/list", response_model=list[SessionResponse])
def list_sessions_explicit(db: Session = Depends(get_db)):
    """Alias explicito para evitar problemas de routing con slash final."""
    return SessionRepository.list_recent(db, limit=50)


@router.get("/active", response_model=list[SessionResponse])
def list_active_sessions(db: Session = Depends(get_db)):
    sessions = SessionRepository.list_recent(db, limit=100)
    return [item for item in sessions if not item.ended_at]

@router.post("/start", response_model=SessionResponse)
def start_session(payload: SessionCreate, db: Session = Depends(get_db)):
    profile = ProfileRepository.get_by_id(db, payload.profile_id)
    scenario = ScenarioRepository.get_by_id(db, payload.scenario_id)

    if not profile or not scenario:
        raise HTTPException(status_code=404, detail="Profile or Scenario not found")

    return SessionRepository.start(db, profile.id, scenario)

@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: UUID, db: Session = Depends(get_db)):
    session = SessionRepository.get_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session

@router.patch("/{session_id}/end")
def end_session(
    session_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Finaliza una sesión de práctica clínica.
    No permite más interacción una vez cerrada.
    """

    session = SessionRepository.get_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.ended_at:
        raise HTTPException(status_code=400, detail="Session already ended")

    session.ended_at = datetime.utcnow()
    db.commit()

    return {
        "message": "Session ended successfully",
        "session_id": session.id,
        "ended_at": session.ended_at
    }