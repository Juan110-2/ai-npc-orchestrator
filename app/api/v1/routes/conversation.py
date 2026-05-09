import json
from datetime import datetime, timezone
from typing import AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.profile_repository import ProfileRepository
from app.repositories.scenario_repository import ScenarioRepository
from app.repositories.sessions_repository import SessionRepository
from app.schemas.conversation_message import ConversationInput, ConversationMessageResponse
from app.services.conversation_heuristics import ConversationHeuristics, MessageCategory
from app.services.intervention_evaluator import evaluate_intervention
from app.services.orchestrator import ConversationOrchestrator

router = APIRouter(prefix="/conversation", tags=["conversation"])

heuristics = ConversationHeuristics()


def _resolve_session_context(session_id: UUID, db: Session):
    """Valida y retorna sesión, perfil y escenario. Lanza HTTPException si algo falta."""
    session = SessionRepository.get_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.ended_at:
        raise HTTPException(status_code=400, detail="Session is already closed")

    profile = ProfileRepository.get_by_id(db, session.profile_id)
    scenario = ScenarioRepository.get_by_id(db, session.scenario_id)

    if not profile or not scenario:
        raise HTTPException(status_code=404, detail="Profile or Scenario not found")

    return session, profile, scenario


def _apply_heuristics_and_evaluator(
    db: Session,
    session,
    user_input: str,
) -> object:
    """
    Aplica heurísticas de turno y evaluador secundario.
    Actualiza session.current_severity y session.ended_at si corresponde.
    Hace commit. Retorna la decisión heurística.
    """
    decision = heuristics.decide(
        user_text=user_input,
        current_severity=session.current_severity,
    )
    session.current_severity = decision.next_severity

    # Segunda señal semántica para categorías ambiguas (evita severidad congelada)
    if decision.category in (
        MessageCategory.NEUTRAL,
        MessageCategory.CONFUSING,
        MessageCategory.INDIFFERENT,
    ):
        try:
            eval_data = evaluate_intervention(user_input)
            impact = int(eval_data.get("overall_impact", 0))
        except Exception:
            impact = 0

        if impact != 0:
            # La indiferencia no debe provocar mejora artificial por ruido del evaluador
            safe_impact = impact
            if decision.category == MessageCategory.INDIFFERENT and impact < 0:
                safe_impact = 0
            session.current_severity = max(0, min(5, session.current_severity + safe_impact))

    if decision.should_close or session.current_severity <= 0:
        session.current_severity = max(0, session.current_severity)
        session.ended_at = datetime.now(timezone.utc)

    db.commit()
    return decision


# ── Endpoint síncrono (request/response completo) ────────────────────────────

@router.post("/{session_id}", response_model=ConversationMessageResponse)
def converse(
    session_id: UUID,
    payload: ConversationInput,
    db: Session = Depends(get_db),
):
    """
    Procesa un turno de conversación y devuelve la respuesta del NPC completa.
    Registra métricas reales de IA (proveedor, modelo, tokens, latencia) en BD.
    """
    session, profile, scenario = _resolve_session_context(session_id, db)

    user_input = payload.content.strip()
    if not user_input:
        raise HTTPException(status_code=400, detail="Missing content")

    # Guardar turno del estudiante antes de procesar (garantiza historial completo para el LLM)
    ConversationRepository.add(
        db=db,
        session_id=session.id,
        role="trainee",
        content=user_input,
        severity=session.current_severity,
        risk_flags=[],
    )

    decision = _apply_heuristics_and_evaluator(db, session, user_input)

    context_history = ConversationRepository.list_by_session(db=db, session_id=session.id)

    # Generar respuesta del NPC — retorna AIResponse con métricas
    ai_response = ConversationOrchestrator.respond(
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

    # Persistir respuesta del