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
from app.services.conversation_heuristics import ConversationHeuristics, MessageCategory
from app.services.intervention_evaluator import evaluate_intervention

router = APIRouter(
    prefix="/conversation",
    tags=["conversation"]
)

heuristics = ConversationHeuristics()

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

    # Guardar el turno del usuario antes de procesar para asegurar que el historial esté completo.
    ConversationRepository.add(
        db=db,
        session_id=session.id,
        role="trainee",
        content=user_input,
        severity=session.current_severity,
        risk_flags=[]
    )

    decision = heuristics.decide(
        user_text=user_input,
        current_severity=session.current_severity,
    )

    session.current_severity = decision.next_severity

    if decision.category in (MessageCategory.NEUTRAL, MessageCategory.CONFUSING, MessageCategory.INDIFFERENT):
        # Segunda señal semántica para categorías ambiguas.
        # Sirve para evitar que la severidad se quede estancada.
        try:
            eval_data = evaluate_intervention(user_input)
            impact = int(eval_data.get("overall_impact", 0))
        except Exception:
            impact = 0

        if impact != 0:
            # La indiferencia no debería mejorar el estado por ruido del evaluador.
            safe_impact = impact
            if decision.category == MessageCategory.INDIFFERENT and impact < 0:
                safe_impact = 0
            session.current_severity = max(1, min(5, session.current_severity + safe_impact))

    if decision.should_close:
        session.ended_at = datetime.utcnow()
    db.commit()

    context_history = ConversationRepository.list_by_session(
        db=db,
        session_id=session.id,
    )

    # La respuesta del paciente es generada al final para facilitar la trazabilidad del proceso.
    response_text = ConversationOrchestrator.respond(
        profile=profile,
        scenario=scenario,
        current_severity=session.current_severity,
        user_input=user_input,
        conversation_history=context_history,
        response_mode=decision.response_mode.value,
        max_sentences=decision.max_sentences,
        should_rotate_focus=decision.should_rotate_focus,
        category=decision.category.value,
    )

    if session.current_severity <= 0:
        session.current_severity = 0
        session.ended_at = datetime.utcnow()
        db.commit()

    # La respuesta del paciente se guarda al final para que el historial refleje el estado después de aplicar las reglas heurísticas.
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