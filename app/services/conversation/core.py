from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.profile_repository import ProfileRepository
from app.repositories.scenario_repository import ScenarioRepository
from app.repositories.sessions_repository import SessionRepository
from app.services.conversation.constants import (
    ABUSE_HISTORY_WINDOW,
    EVALUATOR_SCALE,
    HISTORY_LIMIT,
    MAX_CLOSING_TURNS,
    PARALLEL_TIMEOUT_S,
)
from app.services.conversation.models import TurnContext
from app.services.conversation.heuristics import (
    ConversationHeuristics,
    HeuristicDecision,
    MessageCategory,
)
from app.services.conversation.intervention_evaluator import evaluate_intervention
from app.services.conversation.orchestrator import ConversationOrchestrator

logger = logging.getLogger(__name__)
heuristics = ConversationHeuristics()


def resolve_session_context(session_id: UUID, db: Session):
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


def validate_user_input(content: str) -> str:
    user_input = (content or "").strip()
    if not user_input:
        raise HTTPException(status_code=400, detail="Missing content")
    return user_input


def get_behavior_range(profile) -> tuple[float, float]:
    behavior = (profile.behavior or {}) if profile and hasattr(profile, "behavior") else {}
    b_min = float(behavior.get("behavior_min", 0.0))
    b_max = float(behavior.get("behavior_max", 5.0))
    if b_min >= b_max:
        return 0.0, 5.0
    return b_min, b_max


def fetch_parallel_inputs(
    session_id: UUID,
    current_sev: float,
    user_input: str,
    trainee_msg_id: UUID,
) -> tuple[HeuristicDecision, float]:
    normalized, is_abuse = ConversationHeuristics.prepare_inputs(user_input)

    def semantic_task():
        db = SessionLocal()
        try:
            return heuristics.classify(normalized, db=db, session_id=session_id)
        except Exception:
            logger.warning("[classifier] Tarea semantica fallo (session=%s)", session_id, exc_info=True)
            return None
        finally:
            db.close()

    def recurrence_task() -> bool:
        db = SessionLocal()
        try:
            recent_all = ConversationRepository.list_recent_by_session(
                db=db,
                session_id=session_id,
                limit=ABUSE_HISTORY_WINDOW * 2,
            )
            prior_trainee = [
                message
                for message in recent_all
                if getattr(message, "role", "") == "trainee" and message.id != trainee_msg_id
            ]
            abuse_count = sum(
                1
                for message in prior_trainee
                if ConversationHeuristics._is_explicit_abuse(
                    ConversationHeuristics._normalize(getattr(message, "content", "") or "")
                )
            )
            return abuse_count >= 2
        except Exception:
            logger.warning("[recurrence] Tarea de reincidencia fallo (session=%s)", session_id, exc_info=True)
            return False
        finally:
            db.close()

    def evaluate_task() -> float:
        db = SessionLocal()
        try:
            data = evaluate_intervention(user_input, db=db, session_id=session_id)
            if not isinstance(data, dict):
                return 0.0
            return float(data.get("overall_impact", 0.0))
        except Exception:
            logger.warning("[evaluator] Tarea de evaluacion fallo (session=%s)", session_id, exc_info=True)
            return 0.0
        finally:
            db.close()

    workers = 3 if is_abuse else 2
    executor = ThreadPoolExecutor(max_workers=workers)
    try:
        future_semantic = executor.submit(semantic_task)
        future_evaluation = executor.submit(evaluate_task)
        future_recurrence = executor.submit(recurrence_task) if is_abuse else None

        semantic_result = _resolve_future_result(
            future_semantic,
            default=None,
            timeout_message="[classifier] Timeout en clasificacion semantica (session=%s)",
            error_message="[classifier] Error en clasificacion semantica (session=%s)",
            session_id=session_id,
        )
        impact = _resolve_future_result(
            future_evaluation,
            default=0.0,
            timeout_message="[evaluator] Timeout en evaluacion de intervencion (session=%s)",
            error_message="[evaluator] Error en evaluacion de intervencion (session=%s)",
            session_id=session_id,
        )
        repeat_abuse = False
        if future_recurrence is not None:
            repeat_abuse = _resolve_future_result(
                future_recurrence,
                default=False,
                timeout_message="[recurrence] Timeout en deteccion de reincidencia (session=%s)",
                error_message="[recurrence] Error en deteccion de reincidencia (session=%s)",
                session_id=session_id,
            )
    finally:
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            executor.shutdown(wait=False)

    decision = heuristics.decide_from_parts(
        user_text=user_input,
        current_severity=current_sev,
        semantic_result=semantic_result,
        is_abuse=is_abuse,
        repeat_abuse=repeat_abuse,
    )
    return decision, impact


def _resolve_future_result(
    future,
    *,
    default,
    timeout_message: str,
    error_message: str,
    session_id: UUID,
):
    try:
        return future.result(timeout=PARALLEL_TIMEOUT_S)
    except FuturesTimeoutError:
        logger.warning(timeout_message, session_id)
        return default
    except Exception:
        logger.warning(error_message, session_id, exc_info=True)
        return default


def apply_severity(
    session,
    decision: HeuristicDecision,
    impact: float,
    profile,
    db: Session,
) -> None:
    session.current_severity = decision.next_severity

    if decision.category in (
        MessageCategory.SUPPORTIVE,
        MessageCategory.NEUTRAL,
        MessageCategory.CONFUSING,
        MessageCategory.INDIFFERENT,
    ) and impact != 0.0:
        safe_impact = impact * EVALUATOR_SCALE
        if decision.category == MessageCategory.SUPPORTIVE:
            safe_impact = min(safe_impact, 0.0)
        elif decision.category == MessageCategory.INDIFFERENT:
            safe_impact = max(safe_impact, 0.0)
        session.current_severity += safe_impact

    b_min, b_max = get_behavior_range(profile)
    session.current_severity = max(b_min, min(b_max, float(session.current_severity)))
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.error(
            "[apply_severity] Fallo commit de severidad (session=%s, sev=%.2f)",
            session.id,
            session.current_severity,
            exc_info=True,
        )
        raise


def compute_closing_state(
    current_severity: float,
    context_history: list,
    decision=None,
    *,
    previous_severity: float | None = None,
    base_severity: float | None = None,
    b_min: float = 0.0,
    b_max: float = 5.0,
) -> dict | None:
    # El techo usa el mismo colchón de 0.5 que el piso: un turno de RIESGO que
    # sube la severidad a, por ejemplo, 4.8 (sin tocar el 5 exacto) debe entrar
    # igual a la fase de gracia, no quedarse fuera por no llegar al numero exacto.
    top_threshold = b_max - 0.5
    at_bottom = current_severity <= b_min + 0.5
    at_top = current_severity >= top_threshold
    if not at_bottom and not at_top:
        return None

    crossed_this_turn = (
        previous_severity is not None
        and (
            (at_bottom and previous_severity > b_min + 0.5 and current_severity <= b_min + 0.5)
            or (at_top and previous_severity < top_threshold and current_severity >= top_threshold)
        )
    )

    # Nota: ya no hay una guarda aparte para "escenario que arranca en el limite".
    # El chequeo de mas abajo (not crossed_this_turn and patient_turns == 0) ya
    # cubre exactamente ese caso -- turno 1 sin historial previo en la frontera,
    # sin cruce fresco, no cuenta. Una guarda aparte comparando previous_severity
    # contra el limite se queda "encendida" indefinidamente en un caso de crisis
    # que ronda el techo sin bajar del todo, y la sesion nunca llega a la fase de
    # gracia ni se despide -- por eso se quito.

    boundary_check = (
        (lambda sev: sev <= b_min + 0.5)
        if at_bottom
        else (lambda sev: sev >= top_threshold)
    )

    patient_turns = 0
    for message in reversed(context_history):
        if message.role != "patient":
            continue
        if boundary_check(message.severity):
            patient_turns += 1
        else:
            break

    if not crossed_this_turn and patient_turns == 0:
        return None

    if at_bottom:
        kind = "success"
    elif decision and decision.category == MessageCategory.INAPPROPRIATE:
        kind = "inappropriate"
    elif decision and decision.category == MessageCategory.RISK:
        kind = "crisis_riesgo"
    else:
        kind = "crisis"

    return {
        "kind": kind,
        "patient_turns": patient_turns,
        "reached_boundary_this_turn": crossed_this_turn,
    }


def apply_closed_session_state(session, ctx: TurnContext) -> None:
    if ctx.closing_kind == "success":
        session.current_severity = ctx.b_min
    elif ctx.closing_kind == "crisis":
        session.current_severity = ctx.b_max
    session.status = "terminated" if ctx.closing_kind in ("crisis", "inappropriate") else "completed"
    session.ended_at = datetime.now(timezone.utc)


def commit_with_rollback(
    db: Session,
    error_message: str,
    session_id,
    *,
    reraise: bool = False,
) -> bool:
    try:
        db.commit()
        return True
    except Exception:
        db.rollback()
        logger.error(error_message, session_id, exc_info=True)
        if reraise:
            raise
        return False


def finalize_session_time_safely(db: Session, session, *, source: str) -> None:
    from app.services.sessions.time_service import finalize_session_time

    try:
        finalize_session_time(db, session)
        commit_with_rollback(
            db,
            f"[{source}] Error finalizando tiempo (session=%s)",
            session.id,
        )
    except Exception:
        db.rollback()
        logger.error("[%s] Error finalizando tiempo (session=%s)", source, session.id, exc_info=True)


def finalize_session(session, ctx: TurnContext, db: Session) -> None:
    apply_closed_session_state(session, ctx)
    if not commit_with_rollback(
        db,
        "[finalize_session] Fallo commit (session=%s)",
        session.id,
        reraise=True,
    ):
        return
    finalize_session_time_safely(db, session, source="finalize_session")


def finalize_session_in_generator(gen_db: Session, session_id: UUID, ctx: TurnContext) -> None:
    session = SessionRepository.get_by_id(gen_db, session_id)
    if not session:
        logger.error("No se encontro la sesion %s al finalizar desde el generador", session_id)
        return
    apply_closed_session_state(session, ctx)
    if not commit_with_rollback(
        gen_db,
        "[finalize_session_in_generator] Fallo commit (session=%s)",
        session_id,
    ):
        return
    finalize_session_time_safely(gen_db, session, source="finalize_session_in_generator")


def process_turn(session, profile, user_input: str, db: Session) -> TurnContext:
    try:
        return _process_turn_inner(session, profile, user_input, db)
    except HTTPException:
        raise
    except Exception:
        logger.error(
            "[process_turn] Error inesperado procesando turno (session=%s)",
            session.id,
            exc_info=True,
        )
        raise


def _process_turn_inner(session, profile, user_input: str, db: Session) -> TurnContext:
    b_min, b_max = get_behavior_range(profile)
    previous_severity = float(session.current_severity)
    base_severity = float(
        session.base_severity if session.base_severity is not None else session.current_severity
    )

    trainee_msg = ConversationRepository.add(
        db=db,
        session_id=session.id,
        role="trainee",
        content=user_input,
        severity=session.current_severity,
        risk_flags=[],
    )
    trainee_msg_id: UUID = trainee_msg.id
    db.commit()

    decision, impact = fetch_parallel_inputs(
        session.id,
        previous_severity,
        user_input,
        trainee_msg_id,
    )
    apply_severity(session, decision, impact, profile, db)
    final_severity = float(session.current_severity)
    context_history = ConversationRepository.list_recent_by_session(
        db=db,
        session_id=session.id,
        limit=HISTORY_LIMIT,
    )

    forced_close = decision.should_close
    closing = compute_closing_state(
        final_severity,
        context_history,
        decision,
        previous_severity=previous_severity,
        base_severity=base_severity,
        b_min=b_min,
        b_max=b_max,
    )

    # forced_close solo es True para abuso reincidente (heuristics.py): ese es el
    # unico caso que se salta la fase de gracia y cierra en el mismo turno, con
    # dignidad para el estudiante que ya recibio el limite. Cualquier otro cierre
    # (riesgo, colapso emocional, primer trato inadecuado) pasa por la fase de
    # gracia de compute_closing_state, que da MAX_CLOSING_TURNS antes de despedirse.
    should_close = False
    closing_kind: str | None = None
    if forced_close:
        should_close = True
        closing_kind = "inappropriate"
    elif closing is not None:
        closing_kind = closing["kind"]
        if closing["patient_turns"] >= MAX_CLOSING_TURNS - 1:
            should_close = True

    behavioral_flags: list[str] = []
    if decision.category == MessageCategory.INAPPROPRIATE:
        behavioral_flags.append("abuse")
        if "recurrence:repeat_abuse" in decision.matched_rules:
            behavioral_flags.append("repeat_abuse")
    elif decision.category == MessageCategory.RISK:
        behavioral_flags.append("risk")
    elif decision.category == MessageCategory.RISK_CHECK:
        behavioral_flags.append("risk_check")

    return TurnContext(
        decision=decision,
        forced_close=forced_close,
        closing=closing,
        should_close=should_close,
        closing_kind=closing_kind,
        context_history=context_history,
        final_severity=final_severity,
        b_min=b_min,
        b_max=b_max,
        behavioral_flags=tuple(behavioral_flags),
    )


def generate_sync_ai_response(
    *,
    session,
    profile,
    scenario,
    user_input: str,
    ctx: TurnContext,
    db: Session,
):
    if ctx.should_close:
        return ConversationOrchestrator.contextual_closing_response(
            profile=profile,
            scenario=scenario,
            current_severity=ctx.final_severity,
            closing_kind=ctx.closing_kind,
            conversation_history=ctx.context_history,
            user_input=user_input,
            response_mode=ctx.decision.response_mode.value,
            max_sentences=ctx.decision.max_sentences,
            should_rotate_focus=ctx.decision.should_rotate_focus,
            db=db,
            session_id=session.id,
        )

    if ctx.closing is not None:
        turns_left = MAX_CLOSING_TURNS - ctx.closing["patient_turns"]
        return ConversationOrchestrator.respond_closing_phase(
            profile=profile,
            scenario=scenario,
            current_severity=ctx.final_severity,
            user_input=user_input,
            conversation_history=ctx.context_history,
            closing_kind=ctx.closing_kind,
            turns_left=turns_left,
            db=db,
            session_id=session.id,
        )

    return ConversationOrchestrator.respond(
        profile=profile,
        scenario=scenario,
        current_severity=ctx.final_severity,
        user_input=user_input,
        conversation_history=ctx.context_history,
        response_mode=ctx.decision.response_mode.value,
        max_sentences=ctx.decision.max_sentences,
        should_rotate_focus=ctx.decision.should_rotate_focus,
        db=db,
        session_id=session.id,
    )


def persist_patient_message(
    *,
    db: Session,
    session_id: UUID,
    ctx: TurnContext,
    content: str,
    ai_provider: str | None,
    ai_model: str | None,
    tokens_input: int | None,
    tokens_output: int | None,
    tokens_used: int | None,
    latency_ms: float | None,
):
    return ConversationRepository.add(
        db=db,
        session_id=session_id,
        role="patient",
        content=content,
        severity=ctx.final_severity,
        risk_flags=list(ctx.behavioral_flags),
        ai_provider=ai_provider,
        ai_model=ai_model,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        tokens_used=tokens_used,
        latency_ms=latency_ms,
    )


def commit_patient_message(db: Session, session_id: UUID) -> None:
    commit_with_rollback(
        db,
        "[converse] Fallo commit del patient_msg (session=%s)",
        session_id,
        reraise=True,
    )


def run_auto_evaluation_safely(db: Session, session_id: UUID, source: str) -> None:
    try:
        from app.services.evaluation.service import run_auto_evaluation

        run_auto_evaluation(db, session_id)
    except Exception:
        logger.warning("[%s] run_auto_evaluation fallo", source, exc_info=True)


def finalize_and_evaluate_sync(session, ctx: TurnContext, db: Session) -> None:
    if not ctx.should_close:
        return
    finalize_session(session, ctx, db)
    run_auto_evaluation_safely(db, session.id, "converse")
