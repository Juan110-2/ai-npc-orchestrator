import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db
from app.core.database import SessionLocal
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.profile_repository import ProfileRepository
from app.repositories.scenario_repository import ScenarioRepository
from app.repositories.sessions_repository import SessionRepository
from app.schemas.conversation_message import ConversationInput, ConversationMessageResponse
from app.services.conversation_heuristics import (
    ConversationHeuristics,
    HeuristicDecision,
    MessageCategory,
)
from app.services.intervention_evaluator import evaluate_intervention
from app.services.orchestrator import ConversationOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversation", tags=["conversation"])
heuristics = ConversationHeuristics()

_MAX_CLOSING_TURNS = 3
_EVALUATOR_SCALE = 0.3
_ABUSE_HISTORY_WINDOW = 10
_PARALLEL_TIMEOUT_S = 10.0
_MAX_RESPONSE_CHARS = 8_000
# Mensajes recientes para contexto de IA y lógica de cierre.
# Con _MAX_CLOSING_TURNS=3, el ciclo de cierre cabe holgadamente en este límite.
_HISTORY_LIMIT = 10

_CLOSING_INSTR: dict[str, str] = {
    "success": (
        "La conversación ha logrado calmarte. Despídete agradeciendo de manera "
        "concreta por la ayuda recibida sobre tu situación específica "
        "(menciónala brevemente). Expresa alivio real y un cierre amable. "
        "No introduzcas problemas nuevos."
    ),
    "crisis": (
        "Estás en crisis emocional intensa (severidad 5). No puedes sostener "
        "más la conversación. Despídete brevemente mencionando que tu situación "
        "concreta te tiene desbordado y que necesitas parar ahora. "
        "Tono breve, emocional, sin agresividad."
    ),
    "inappropriate": (
        "El usuario te trató de manera inadecuada y vas a cerrar la conversación "
        "con dignidad. Despídete brevemente marcando un límite claro y firme. "
        "Sin agresividad, pero con firmeza. Una o dos frases máximo."
    ),
}


@dataclass(frozen=True)
class TurnContext:
    """Estado computado de un turno. Compartido entre converse y converse_stream."""
    decision: HeuristicDecision
    forced_close: bool
    closing: dict | None
    should_close: bool
    closing_kind: str | None
    context_history: list
    final_severity: float
    b_min: float
    b_max: float
    # Flags conductuales independientes de la severidad emocional.
    behavioral_flags: tuple[str, ...]


@dataclass(frozen=True)
class StreamInputs:
    """Entradas preparadas para el generador SSE."""
    system_prompt: str | None
    effective_user_input: str
    forced_text: str | None


# ---------------------------------------------------------------------------
# Helpers de infraestructura
# ---------------------------------------------------------------------------

def _resolve_session_context(session_id: UUID, db: Session):
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


def _get_behavior_range(profile) -> tuple[float, float]:
    b = (profile.behavior or {}) if profile and hasattr(profile, "behavior") else {}
    b_min = float(b.get("behavior_min", 0.0))
    b_max = float(b.get("behavior_max", 5.0))
    if b_min >= b_max:
        return 0.0, 5.0
    return b_min, b_max


def _safe_accumulate(current: str, chunk: str) -> str:
    """Acumula texto hasta _MAX_RESPONSE_CHARS; descarta excedente para acotar memoria."""
    remaining = _MAX_RESPONSE_CHARS - len(current)
    if remaining <= 0:
        return current
    return current + chunk[:remaining]


# ---------------------------------------------------------------------------
# Tareas paralelas
# ---------------------------------------------------------------------------

def _fetch_parallel_inputs(
    session_id: UUID,
    current_sev: float,
    user_input: str,
    trainee_msg_id: UUID,
) -> tuple[HeuristicDecision, float]:
    """
    Ejecuta en paralelo clasificación semántica, evaluación de intervención y
    (solo si hay abuso léxico) detección de reincidencia. Cada tarea usa su
    propia conexión BD independiente para evitar contención de sesión.
    """
    normalized, is_abuse = ConversationHeuristics.prepare_inputs(user_input)

    def _semantic_task():
        d = SessionLocal()
        try:
            return heuristics.classify(normalized, db=d, session_id=session_id)
        except Exception:
            logger.warning("Tarea semántica falló", exc_info=True)
            return None
        finally:
            d.close()

    def _recurrence_task() -> bool:
        d = SessionLocal()
        try:
            recent_all = ConversationRepository.list_recent_by_session(
                db=d, session_id=session_id, limit=_ABUSE_HISTORY_WINDOW * 2
            )
            # Excluir el mensaje actual del conteo: reincidencia = 2+ mensajes previos abusivos.
            prior_trainee = [
                m for m in recent_all
                if getattr(m, "role", "") == "trainee" and m.id != trainee_msg_id
            ]
            abuse_count = sum(
                1 for m in prior_trainee
                if ConversationHeuristics._is_explicit_abuse(
                    ConversationHeuristics._normalize(getattr(m, "content", "") or "")
                )
            )
            return abuse_count >= 2
        except Exception:
            logger.warning("Tarea de reincidencia falló", exc_info=True)
            return False
        finally:
            d.close()

    def _evaluate_task() -> float:
        d = SessionLocal()
        try:
            data = evaluate_intervention(user_input, db=d, session_id=session_id)
            if not isinstance(data, dict):
                return 0.0
            return float(data.get("overall_impact", 0.0))
        except Exception:
            logger.warning("Tarea de evaluación de intervención falló", exc_info=True)
            return 0.0
        finally:
            d.close()

    # FIX E: executor manual para que shutdown(wait=False) no bloquee tras el timeout.
    n_workers = 3 if is_abuse else 2
    executor = ThreadPoolExecutor(max_workers=n_workers)
    try:
        fut_sem = executor.submit(_semantic_task)
        fut_evl = executor.submit(_evaluate_task)
        fut_rec = executor.submit(_recurrence_task) if is_abuse else None

        try:
            semantic_result = fut_sem.result(timeout=_PARALLEL_TIMEOUT_S)
        except FuturesTimeoutError:
            logger.warning("Timeout en clasificación semántica")
            semantic_result = None
        except Exception:
            logger.warning("Error en clasificación semántica", exc_info=True)
            semantic_result = None

        try:
            impact = fut_evl.result(timeout=_PARALLEL_TIMEOUT_S)
        except FuturesTimeoutError:
            logger.warning("Timeout en evaluación de intervención")
            impact = 0.0
        except Exception:
            logger.warning("Error en evaluación de intervención", exc_info=True)
            impact = 0.0

        repeat_abuse = False
        if fut_rec is not None:
            try:
                repeat_abuse = fut_rec.result(timeout=_PARALLEL_TIMEOUT_S)
            except FuturesTimeoutError:
                logger.warning("Timeout en detección de reincidencia")
            except Exception:
                logger.warning("Error en detección de reincidencia", exc_info=True)
    finally:
        # cancel_futures disponible desde Python 3.9; fallback para versiones anteriores.
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


# ---------------------------------------------------------------------------
# Severidad
# ---------------------------------------------------------------------------

def _apply_severity(
    session, decision: HeuristicDecision, impact: float, profile, db: Session
) -> None:
    """
    Aplica la decisión heurística y el impacto del evaluador sobre current_severity.

    La dirección del impacto se alinea con la semántica de la categoría para evitar
    que el evaluador invierta el efecto de la decisión heurística:
      - SUPPORTIVE: impacto solo puede reducir (impacto positivo = contradicción, descartado).
      - INDIFFERENT: impacto solo puede aumentar (impacto negativo = contradicción, descartado).
      - NEUTRAL / CONFUSING: sin restricción de dirección.
      - INAPPROPRIATE / INVALIDATING / RISK: exentos; la heurística ya los gestiona.
    """
    session.current_severity = decision.next_severity

    if decision.category in (
        MessageCategory.SUPPORTIVE,
        MessageCategory.NEUTRAL,
        MessageCategory.CONFUSING,
        MessageCategory.INDIFFERENT,
    ) and impact != 0.0:
        safe_impact = impact * _EVALUATOR_SCALE
        if decision.category == MessageCategory.SUPPORTIVE:
            safe_impact = min(safe_impact, 0.0)
        elif decision.category == MessageCategory.INDIFFERENT:
            safe_impact = max(safe_impact, 0.0)
        session.current_severity += safe_impact

    b_min, b_max = _get_behavior_range(profile)
    session.current_severity = max(b_min, min(b_max, float(session.current_severity)))
    # FIX F: rollback explícito si el commit falla.
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


# ---------------------------------------------------------------------------
# Lógica de cierre
# ---------------------------------------------------------------------------

def _compute_closing_state(
    current_severity: float,
    context_history: list,
    decision=None,
    *,
    previous_severity: float | None = None,
    base_severity: float | None = None,
    b_min: float = 0.0,
    b_max: float = 5.0,
) -> dict | None:
    at_bottom = current_severity <= b_min + 0.5
    at_top = current_severity >= b_max

    if not at_bottom and not at_top:
        return None

    started_at_bottom = base_severity is not None and base_severity <= b_min + 0.5
    started_at_top = base_severity is not None and base_severity >= b_max

    crossed_this_turn = (
        previous_severity is not None
        and (
            (at_bottom and previous_severity > b_min + 0.5 and current_severity <= b_min + 0.5)
            or (at_top and previous_severity < b_max and current_severity >= b_max)
        )
    )

    # Ignorar el límite solo si la sesión arrancó allí Y sigue ahí sin haber
    # salido nunca. Si salió y volvió (crossed_this_turn = True), es ciclo nuevo.
    ignore_initial_boundary = (
        previous_severity is not None
        and not crossed_this_turn
        and (
            (at_bottom and started_at_bottom and previous_severity <= b_min + 0.5)
            or (at_top and started_at_top and previous_severity >= b_max)
        )
    )
    if ignore_initial_boundary:
        return None

    if at_bottom:
        boundary_check = lambda s: s <= b_min + 0.5
    else:
        boundary_check = lambda s: s >= b_max

    # Contar turnos consecutivos del paciente en el límite activo.
    # Iteración inversa con break para contar solo el ciclo actual.
    patient_turns = 0
    for msg in reversed(context_history):
        if msg.role != "patient":
            continue
        if boundary_check(msg.severity):
            patient_turns += 1
        else:
            break

    if not crossed_this_turn and patient_turns == 0:
        return None

    if at_bottom:
        kind = "success"
    else:
        kind = (
            "inappropriate"
            if decision and decision.category == MessageCategory.INAPPROPRIATE
            else "crisis"
        )

    return {
        "kind": kind,
        "patient_turns": patient_turns,
        "reached_boundary_this_turn": crossed_this_turn,
    }


def _finalize_session(session, ctx: TurnContext, db: Session) -> None:
    """Pina severidad final y marca sesión cerrada usando la sesión BD del request."""
    if ctx.closing_kind == "success":
        session.current_severity = ctx.b_min
    elif ctx.closing_kind == "crisis":
        session.current_severity = ctx.b_max
    # "inappropriate" o None: severidad queda en el valor real del momento del cierre.
    session.ended_at = datetime.now(timezone.utc)
    # FIX F: rollback explícito si el commit falla.
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.error("[_finalize_session] Falló commit al cerrar sesión", exc_info=True)
        raise


def _finalize_session_in_generator(
    gen_db: Session, session_id: UUID, ctx: TurnContext
) -> None:
    """
    Versión del cierre para el generador SSE, que usa su propia sesión BD.
    Re-fetch necesario porque gen_db no comparte estado con la sesión del request.
    """
    sess_obj = SessionRepository.get_by_id(gen_db, session_id)
    if not sess_obj:
        logger.error("No se encontró la sesión %s al finalizar desde el generador", session_id)
        return
    if ctx.closing_kind == "success":
        sess_obj.current_severity = ctx.b_min
    elif ctx.closing_kind == "crisis":
        sess_obj.current_severity = ctx.b_max
    # "inappropriate" o None: severidad queda en el valor real del momento del cierre.
    sess_obj.ended_at = datetime.now(timezone.utc)
    # FIX F: rollback explícito si el commit falla.
    try:
        gen_db.commit()
    except Exception:
        gen_db.rollback()
        logger.error(
            "[_finalize_session_in_generator] Falló commit al cerrar sesión", exc_info=True
        )


# ---------------------------------------------------------------------------
# Núcleo compartido
# ---------------------------------------------------------------------------

def _process_turn(
    session,
    profile,
    user_input: str,
    db: Session,
) -> TurnContext:
    """
    Núcleo compartido de converse y converse_stream: persiste el mensaje del
    trainee, ejecuta tareas paralelas, actualiza severidad y computa estado de cierre.
    """
    b_min, b_max = _get_behavior_range(profile)
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
    # ID capturado antes del commit explícito para evitar expiración del objeto ORM.
    trainee_msg_id: UUID = trainee_msg.id
    # Commit explícito para garantizar visibilidad del mensaje en las conexiones paralelas.
    db.commit()

    decision, impact = _fetch_parallel_inputs(
        session.id, previous_severity, user_input, trainee_msg_id
    )
    _apply_severity(session, decision, impact, profile, db)
    final_severity = float(session.current_severity)

    context_history = ConversationRepository.list_recent_by_session(
        db=db, session_id=session.id, limit=_HISTORY_LIMIT
    )

    forced_close = decision.should_close
    closing = _compute_closing_state(
        final_severity,
        context_history,
        decision,
        previous_severity=previous_severity,
        base_severity=base_severity,
        b_min=b_min,
        b_max=b_max,
    )

    should_close = False
    closing_kind: str | None = None

    if forced_close and closing is None:
        # Cierre inmediato por abuso reiterado sin alcanzar límite de severidad.
        should_close = True
        closing_kind = "inappropriate"
    elif closing is not None:
        closing_kind = closing["kind"]
        if closing["patient_turns"] >= _MAX_CLOSING_TURNS - 1 or forced_close:
            should_close = True

    # Flags conductuales separados de la severidad emocional.
    behavioral_flags: list[str] = []
    if decision.category == MessageCategory.INAPPROPRIATE:
        behavioral_flags.append("abuse")
        if "recurrence:repeat_abuse" in decision.matched_rules:
            behavioral_flags.append("repeat_abuse")

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


# ---------------------------------------------------------------------------
# Helpers de prompt para streaming
# ---------------------------------------------------------------------------

def _build_final_closing_prompt(
    profile, scenario, kind: str, current_severity: float
) -> str:
    instr = _CLOSING_INSTR.get(kind, "Despídete brevemente.")
    return (
        ConversationOrchestrator._STABLE_PROMPT_HEADER
        + "\n\n[CONTEXTO DEL PERSONAJE]\n"
        + ConversationOrchestrator._format_profile_context(profile, scenario, current_severity)
        + "\n\n[INSTRUCCIÓN DE CIERRE]\n"
        + instr
        + "\n\nMáximo 3 frases. En primera persona. Sin listas, sin etiquetas, en español natural."
    )


def _build_stream_inputs(
    profile, scenario, ctx: TurnContext, user_input: str
) -> StreamInputs:
    """Prepara system_prompt o forced_text para el generador SSE."""
    if ctx.should_close:
        return StreamInputs(
            system_prompt=_build_final_closing_prompt(
                profile, scenario, ctx.closing_kind or "crisis", ctx.final_severity
            ),
            effective_user_input="Despídete ahora cumpliendo todas las reglas anteriores.",
            forced_text=None,
        )

    if ctx.closing is not None:
        turns_left = _MAX_CLOSING_TURNS - ctx.closing["patient_turns"]
        return StreamInputs(
            system_prompt=ConversationOrchestrator.build_closing_phase_prompt(
                profile=profile,
                scenario=scenario,
                current_severity=ctx.final_severity,
                closing_kind=ctx.closing_kind,
                turns_left=turns_left,
            ),
            effective_user_input=user_input,
            forced_text=None,
        )

    forced_text = ConversationOrchestrator._fallback_reactive_response(
        response_mode=ctx.decision.response_mode.value,
        current_severity=ctx.final_severity,
    )
    if forced_text:
        return StreamInputs(
            system_prompt=None,
            effective_user_input=user_input,
            forced_text=forced_text,
        )

    system_prompt, _ = ConversationOrchestrator.build_prompt(
        profile=profile,
        scenario=scenario,
        current_severity=ctx.final_severity,
        response_mode=ctx.decision.response_mode.value,
        max_sentences=ctx.decision.max_sentences,
        should_rotate_focus=ctx.decision.should_rotate_focus,
        category=ctx.decision.category.value,
    )
    return StreamInputs(
        system_prompt=system_prompt,
        effective_user_input=user_input,
        forced_text=None,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/{session_id}", response_model=ConversationMessageResponse)
def converse(
    session_id: UUID,
    payload: ConversationInput,
    db: Session = Depends(get_db),
):
    session, profile, scenario = _resolve_session_context(session_id, db)

    user_input = payload.content.strip()
    if not user_input:
        raise HTTPException(status_code=400, detail="Missing content")

    ctx = _process_turn(session, profile, user_input, db)

    if ctx.should_close:
        ai_response = ConversationOrchestrator.contextual_closing_response(
            profile=profile,
            scenario=scenario,
            current_severity=ctx.final_severity,
            closing_kind=ctx.closing_kind,
            conversation_history=ctx.context_history,
            db=db,
            session_id=session.id,
        )
    elif ctx.closing is not None:
        turns_left = _MAX_CLOSING_TURNS - ctx.closing["patient_turns"]
        ai_response = ConversationOrchestrator.respond_closing_phase(
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
    else:
        ai_response = ConversationOrchestrator.respond(
            profile=profile,
            scenario=scenario,
            current_severity=ctx.final_severity,
            user_input=user_input,
            conversation_history=ctx.context_history,
            response_mode=ctx.decision.response_mode.value,
            max_sentences=ctx.decision.max_sentences,
            should_rotate_focus=ctx.decision.should_rotate_focus,
            category=ctx.decision.category.value,
            db=db,
            session_id=session.id,
        )

    patient_msg = ConversationRepository.add(
        db=db,
        session_id=session.id,
        role="patient",
        content=ai_response.content,
        severity=ctx.final_severity,
        risk_flags=list(ctx.behavioral_flags),
        ai_provider=ai_response.provider,
        ai_model=ai_response.model,
        tokens_input=ai_response.tokens_input,
        tokens_output=ai_response.tokens_output,
        tokens_used=ai_response.tokens_total,
        latency_ms=ai_response.latency_ms,
    )
    # FIX A: commit explícito del patient_msg con rollback controlado.
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Error persisting AI response")

    if ctx.should_close:
        _finalize_session(session, ctx, db)
        try:
            from app.services.evaluation_service import run_auto_evaluation
            run_auto_evaluation(db, session.id)
        except Exception:
            logger.warning("[converse] run_auto_evaluation falló", exc_info=True)

    return patient_msg


@router.post("/{session_id}/stream")
def converse_stream(
    session_id: UUID,
    payload: ConversationInput,
    db: Session = Depends(get_db),
):
    session, profile, scenario = _resolve_session_context(session_id, db)

    user_input = payload.content.strip()
    if not user_input:
        raise HTTPException(status_code=400, detail="Missing content")

    ctx = _process_turn(session, profile, user_input, db)
    stream_in = _build_stream_inputs(profile, scenario, ctx, user_input)
    context_messages = ConversationOrchestrator._build_context_messages(ctx.context_history)

    from app.services.ai.base import StreamResult
    from app.services.ai.metrics_logger import log_ai_call

    def _stream_generator():
        # Sesión BD propia del generador, independiente del ciclo de vida del request.
        # El try/finally garantiza cierre aunque el cliente corte la conexión a mitad.
        gen_db = SessionLocal()
        try:
            accumulated = ""
            provider = "deterministic" if stream_in.forced_text else "unknown"
            model = "fallback" if stream_in.forced_text else "unknown"
            tokens_input = tokens_output = 0
            latency_ms = ttft_ms = 0.0
            # FIX D: capturar excepciones no-StopIteration del generador del stream.
            stream_error: Exception | None = None

            if stream_in.forced_text:
                for word in stream_in.forced_text.split():
                    chunk = word + " "
                    accumulated = _safe_accumulate(accumulated, chunk)
                    # FIX G: evento tipado para chunks.
                    yield f"event: chunk\ndata: {json.dumps({'chunk': chunk})}\n\n"
            else:
                with log_ai_call(
                    gen_db,
                    purpose="orchestrator",
                    session_id=session_id,
                    call_mode="stream",
                ) as log_ctx:
                    prompt_len = (
                        len(stream_in.system_prompt or "")
                        + len(stream_in.effective_user_input)
                    )
                    log_ctx.record_prompt_chars(prompt_len)
                    gen = log_ctx.client.generate_stream(
                        stream_in.system_prompt,
                        stream_in.effective_user_input,
                        context_messages,
                    )
                    stream_result: StreamResult | None = None
                    try:
                        while True:
                            chunk = next(gen)
                            accumulated = _safe_accumulate(accumulated, chunk)
                            # FIX G: evento tipado para chunks.
                            yield f"event: chunk\ndata: {json.dumps({'chunk': chunk})}\n\n"
                    except StopIteration as stop:
                        if isinstance(stop.value, StreamResult):
                            stream_result = stop.value
                    except Exception as exc:
                        # FIX D: captura de errores del stream; no silenciar.
                        stream_error = exc
                        logger.error("[converse_stream] Error en generate_stream", exc_info=True)

                    # FIX C: provider/model siempre desde el cliente si existía;
                    # se ejecuta incluso tras stream_error porque la excepción fue capturada.
                    provider = log_ctx.client.provider
                    model = log_ctx.client.model

                    if stream_result is not None:
                        tokens_input = stream_result.tokens_input
                        tokens_output = stream_result.tokens_output
                        latency_ms = stream_result.latency_ms
                        ttft_ms = stream_result.ttft_ms
                        log_ctx.record_stream_result(stream_result, accumulated)

            # FIX D: si el stream falló, emitir error y persistir parcial si hay contenido.
            if stream_error is not None:
                yield f"event: error\ndata: {json.dumps({'error': str(stream_error)})}\n\n"
                if accumulated.strip():
                    try:
                        ConversationRepository.add(
                            db=gen_db,
                            session_id=session_id,
                            role="patient",
                            content=accumulated.strip(),
                            severity=ctx.final_severity,
                            risk_flags=list(ctx.behavioral_flags),
                            ai_provider=provider,
                            ai_model=model,
                            tokens_input=tokens_input,
                            tokens_output=tokens_output,
                            tokens_used=tokens_input + tokens_output,
                            latency_ms=latency_ms,
                        )
                        gen_db.commit()
                    except Exception:
                        gen_db.rollback()
                        logger.error(
                            "[converse_stream] Falló persistencia del parcial tras error",
                            exc_info=True,
                        )
                return

            # FIX B: commit explícito del patient_msg con rollback controlado.
            try:
                ConversationRepository.add(
                    db=gen_db,
                    session_id=session_id,
                    role="patient",
                    content=accumulated.strip(),
                    severity=ctx.final_severity,
                    risk_flags=list(ctx.behavioral_flags),
                    ai_provider=provider,
                    ai_model=model,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    tokens_used=tokens_input + tokens_output,
                    latency_ms=latency_ms,
                )
                gen_db.commit()
            except Exception:
                gen_db.rollback()
                logger.error("[converse_stream] Falló commit del patient_msg", exc_info=True)
                yield f"event: error\ndata: {json.dumps({'error': 'DB commit failed'})}\n\n"
                return

            if ctx.should_close:
                _finalize_session_in_generator(gen_db, session_id, ctx)
                try:
                    from app.services.evaluation_service import run_auto_evaluation
                    run_auto_evaluation(gen_db, session_id)
                except Exception:
                    logger.warning("[converse_stream] run_auto_evaluation falló", exc_info=True)

            # FIX G: evento done tipado.
            yield (
                "event: done\ndata: "
                + json.dumps({
                    "done": True,
                    "severity": ctx.final_severity,
                    "should_close": ctx.should_close,
                    "closing_kind": ctx.closing_kind,
                    "metrics": {
                        "provider": provider,
                        "model": model,
                        "tokens_input": tokens_input,
                        "tokens_output": tokens_output,
                        "latency_ms": latency_ms,
                        "ttft_ms": ttft_ms,
                    },
                })
                + "\n\n"
            )
        finally:
            gen_db.close()

    return StreamingResponse(
        _stream_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{session_id}/history", response_model=list[ConversationMessageResponse])
def get_conversation_history(
    session_id: UUID,
    db: Session = Depends(get_db),
):
    session = SessionRepository.get_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return ConversationRepository.list_by_session(db, session_id)
