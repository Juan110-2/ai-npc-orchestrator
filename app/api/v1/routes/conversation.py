from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID

from app.api.v1.deps import get_db
from app.schemas.conversation_message import ConversationInput, ConversationMessageResponse
from app.repositories.sessions_repository import SessionRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.profile_repository import ProfileRepository
from app.repositories.scenario_repository import ScenarioRepository
from app.services.orchestrator import ConversationOrchestrator
from app.services.intervention_evaluator import evaluate_intervention
from app.services.severity_manager import adjust_severity

router = APIRouter(
    prefix="/conversation",
    tags=["conversation"]
)

@router.post("/{session_id}", response_model=ConversationMessageResponse)
def converse(
    session_id: UUID,
    payload: ConversationInput,
    db: Session = Depends(get_db)
):
    session = SessionRepository.get_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.ended_at:
        raise HTTPException(status_code=400, detail="Session is already closed")

    profile = ProfileRepository.get_by_id(db, session.profile_id)
    scenario = ScenarioRepository.get_by_id(db, session.scenario_id)

    if not profile or not scenario:
        raise HTTPException(status_code=404, detail="Profile or Scenario not found")

    user_input = payload.content.strip()
    if not user_input:
        raise HTTPException(status_code=400, detail="Missing content")

    # Guardar mensaje del trainee
    ConversationRepository.add(
        db=db,
        session_id=session.id,
        role="trainee",
        content=user_input,
        severity=session.current_severity,
        risk_flags=[]
    )

    try:
        evaluation = evaluate_intervention(user_input)
        impact = evaluation.get("overall_impact", 0)
    except Exception:
        impact = 0  # fallback seguro

    session.current_severity = adjust_severity(
        session.current_severity,
        impact
    )
    db.commit()

    # Generar respuesta del paciente
    response_text = ConversationOrchestrator.respond(
        profile=profile,
        scenario=scenario,
        current_severity=session.current_severity,
        user_input=user_input
    )

    if session.current_severity == 0:
        session.ended_at = datetime.utcnow()
        db.commit()

    if session.current_severity <= 0:
        session.current_severity = 0 
        session.ended_at = datetime.utcnow()
        db.commit()

    # Guardar respuesta del paciente
    patient_msg = ConversationRepository.add(
        db=db,
        session_id=session.id,
        role="patient",
        content=response_text,
        severity=session.current_severity,
        risk_flags=[]
    )

    return patient_msg

@router.get("/{session_id}/history", response_model=list[ConversationMessageResponse])
def get_conversation_history(
    session_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Devuelve todo el historial de una sesión de práctica,
    ordenado cronológicamente.
    """

    session = SessionRepository.get_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return ConversationRepository.list_by_session(db, session_id)