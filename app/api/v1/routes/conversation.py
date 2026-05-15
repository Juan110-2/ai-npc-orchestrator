import json
from datetime import datetime, timezone
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


def _apply_heuristics_and_evaluator(db: Session, session, user_input: str):
    """
    Decide la categoria del turno y aplica el evaluador en PARALELO cuando
    aplica. Cada hilo usa su propia sesion BD para evitar conflictos.

    Reduce ~30-40% la latencia percibida por turno al solapar dos llamadas IA
    que antes eran secuenciales.
    """
    from concurrent.futures import ThreadPoolExecutor
    from app.core.database import SessionLocal

    session_id = session.id
    current_sev = session.current_severity

    def _classify_task() -> object:
        d = SessionLocal()
        try:
            return heuristics.decide(
                user_text=user_input,
                current_severity=current_sev,
                db=d,
                session_id=session_id,
            )
        finally:
            d.close()

    def _evaluate_task() -> int:
        d = SessionLocal()
        try:
            data = evaluate_intervention(user_input, db=d, session_id=session_id)
            return int(data.get("overall_impact", 0))
        except Exception:
            return 0
        finally:
            d.close()

    # Lanzar las DOS llamadas IA en paralelo. El evaluator solo se aplicara
    # despues si la categoria del classifier es ambigua, pero ya tenemos su
    # resultado listo. La penalizacion de lanzar de mas (cuando no aplica)
    # es minima en tokens y compensa con latencia mejor para el caso comun.
    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_classify = ex.submit(_classify_task)
        fut_evaluate = ex.submit(_evaluate_task)
        decision = fut_classify.result()
        impact = fut_evaluate.result()

    session.current_severity = decision.next_severity

    # Aplicar el impact del evaluator solo cuando la categoria es ambigua
    if decision.category in (
        MessageCategory.NEUTRAL,
        MessageCategory.CONFUSING,
        MessageCategory.INDIFFERENT,
    ) and impact != 0:
        safe_impact = impact
        if decision.category == MessageCategory.INDIFFERENT and impact < 0:
            safe_impact = 0
        session.current_severity = max(0, min(5, session.current_severity + safe_impact))

    if decision.should_close or session.current_severity <= 0:
        session.current_severity = max(0, session.current_severity)
        session.ended_at = datetime.now(timezone.utc)

    db.commit()
    return decision


def _infer_closing_kind(decision, final_severity: int) -> str:
    """
    Determina el tipo de cierre para que el NPC se despida con el mensaje correcto.
      - 'success'       : sesion cerrada porque el estudiante ayudo (severity baja).
      - 'crisis'        : sesion cerrada por escalada de crisis.
      - 'inappropriate' : sesion cerrada por conducta inapropiada del estudiante.
    """
    response_mode = decision.response_mode.value
    if response_mode == "crisis" or final_severity >= 5:
        return "crisis"
    if response_mode == "boundary" or decision.category == MessageCategory.INAPPROPRIATE:
        return "inappropriate"
    return "success"


# ----- Endpoint sincrono -----------------------------------------------------

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

    ConversationRepository.add(
        db=db, session_id=session.id, role="trainee",
        content=user_input, severity=session.current_severity, risk_flags=[],
    )

    decision = _apply_heuristics_and_evaluator(db, session, user_input)
    context_history = ConversationRepository.list_by_session(db=db, session_id=session.id)

    # Si la sesion va a cerrar, el NPC se despide CONTEXTUALMENTE (LLM + caso)
    should_close = session.ended_at is not None
    if should_close:
        closing_kind = _infer_closing_kind(decision, session.current_severity)
        ai_response = ConversationOrchestrator.contextual_closing_response(
            profile=profile,
            scenario=scenario,
            current_severity=session.current_severity,
            closing_kind=closing_kind,
            conversation_history=context_history,
            db=db,
            session_id=session.id,
        )
    else:
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
            db=db,
            session_id=session.id,
        )

    patient_msg = ConversationRepository.add(
        db=db, session_id=session.id, role="patient",
        content=ai_response.content,
        severity=session.current_severity, risk_flags=[],
        ai_provider=ai_response.provider, ai_model=ai_response.model,
        tokens_input=ai_response.tokens_input, tokens_output=ai_response.tokens_output,
        tokens_used=ai_response.tokens_total, latency_ms=ai_response.latency_ms,
    )

    # Si cerro la sesion, disparar evaluacion automatica (best-effort)
    if should_close:
        try:
            from app.services.evaluation_service import run_auto_evaluation
            run_auto_evaluation(db, session.id)
        except Exception as e:
            print(f"[converse] run_auto_evaluation fallo: {type(e).__name__}: {e}")

    return patient_msg


# ----- Endpoint SSE streaming ------------------------------------------------

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

    ConversationRepository.add(
        db=db, session_id=session.id, role="trainee",
        content=user_input, severity=session.current_severity, risk_flags=[],
    )

    decision = _apply_heuristics_and_evaluator(db, session, user_input)
    context_history = ConversationRepository.list_by_session(db=db, session_id=session.id)

    final_severity = session.current_severity
    should_close = session.ended_at is not None
    closing_kind = _infer_closing_kind(decision, final_severity) if should_close else None

    # Si NO va a cerrar y hay fallback reactivo, usamos texto deterministico.
    # Si va a cerrar, generamos despedida contextual con LLM (no deterministico).
    forced_text = None
    use_closing_prompt = False
    if should_close:
        use_closing_prompt = True  # generaremos con LLM usando un system prompt de despedida
    else:
        forced_text = ConversationOrchestrator._fallback_reactive_response(
            response_mode=decision.response_mode.value,
            current_severity=final_severity,
        )

    system_prompt = None
    if use_closing_prompt:
        # Construir un system prompt especifico de despedida que use el contexto
        # del paciente. Si el LLM falla, el catch caera al closing_message
        # deterministico.
        from app.services.ai.factory import get_ai_client as _gac
        closing_instr_map = {
            "success": (
                "La conversacion ha logrado calmarte. Tu severidad esta en 0 o 1. "
                "Despidete agradeciendo de manera CONCRETA por la ayuda recibida sobre "
                "tu situacion especifica (mencionala brevemente). Expresa alivio real "
                "y un cierre amable. NO introduzcas problemas nuevos."
            ),
            "crisis": (
                "Estas en crisis emocional intensa (severidad 5). NO puedes sostener "
                "mas la conversacion. Despidete brevemente mencionando que TU situacion "
                "concreta te tiene desbordado y que necesitas parar AHORA. Tono breve, "
                "emocional, sin agresividad."
            ),
            "inappropriate": (
                "El usuario te trato de manera inadecuada y vas a cerrar la conversacion "
                "con dignidad. Despidete brevemente marcando un limite claro y firme. "
                "Sin agresividad, pero con firmeza. Una o dos frases maximo."
            ),
        }
        closing_instr = closing_instr_map.get(closing_kind, "Despidete brevemente.")
        system_prompt = (
            ConversationOrchestrator._STABLE_PROMPT_HEADER
            + "\n\n[CONTEXTO DEL PERSONAJE]\n"
            + ConversationOrchestrator._format_profile_context(profile, scenario, final_severity)
            + "\n\n[INSTRUCCION DE CIERRE]\n"
            + closing_instr
            + "\n\nMaximo 3 frases. En primera persona. Sin listas, sin etiquetas, en espanol natural."
        )
        # Para la despedida usamos un user_prompt de "despidete" en lugar del input
        # del usuario, porque el user_input puede ser el detonante del cierre (ej. insulto).
        user_input = "Despidete ahora cumpliendo todas las reglas anteriores."
    elif not forced_text:
        system_prompt, _ = ConversationOrchestrator.build_prompt(
            profile=profile, scenario=scenario,
            current_severity=final_severity,
            response_mode=decision.response_mode.value,
            max_sentences=decision.max_sentences,
            should_rotate_focus=decision.should_rotate_focus,
            category=decision.category.value,
        )

    from app.services.ai.factory import get_ai_client
    from app.services.ai.base import StreamResult
    from app.services.ai.metrics_logger import log_ai_call

    ai = get_ai_client()
    context_messages = ConversationOrchestrator._build_context_messages(context_history)

    def _stream_generator():
        accumulated = ""
        if forced_text:
            provider, model = "deterministic", "fallback"
        else:
            provider, model = "unknown", "unknown"
        tokens_input = tokens_output = 0
        latency_ms = ttft_ms = 0.0

        if forced_text:
            for word in forced_text.split():
                chunk = word + " "
                accumulated += chunk
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        else:
            with log_ai_call(
                db, purpose="orchestrator",
                session_id=session.id, call_mode="stream",
            ) as ctx:
                ctx.record_prompt_chars(len(system_prompt or "") + len(user_input))
                gen = ctx.client.generate_stream(system_prompt, user_input, context_messages)
                stream_result: StreamResult | None = None
                try:
                    while True:
                        chunk = next(gen)
                        accumulated += chunk
                        yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                except StopIteration as stop:
                    if isinstance(stop.value, StreamResult):
                        stream_result = stop.value

                provider = ctx.client.provider
                model = ctx.client.model
                if stream_result is not None:
                    tokens_input = stream_result.tokens_input
                    tokens_output = stream_result.tokens_output
                    latency_ms = stream_result.latency_ms
                    ttft_ms = stream_result.ttft_ms
                    ctx.record_stream_result(stream_result, accumulated)

        ConversationRepository.add(
            db=db, session_id=session.id, role="patient",
            content=accumulated.strip(),
            severity=final_severity, risk_flags=[],
            ai_provider=provider, ai_model=model,
            tokens_input=tokens_input, tokens_output=tokens_output,
            tokens_used=tokens_input + tokens_output, latency_ms=latency_ms,
        )

        # Si cerro la sesion, disparar evaluacion automatica
        if should_close:
            try:
                from app.services.evaluation_service import run_auto_evaluation
                run_auto_evaluation(db, session.id)
            except Exception as e:
                print(f"[converse_stream] run_auto_evaluation fallo: {type(e).__name__}: {e}")

        yield (
            "data: "
            + json.dumps({
                "done": True,
                "severity": final_severity,
                "should_close": should_close,
                "closing_kind": closing_kind,
                "metrics": {
                    "provider": provider, "model": model,
                    "tokens_input": tokens_input, "tokens_output": tokens_output,
                    "latency_ms": latency_ms, "ttft_ms": ttft_ms,
                },
            })
            + "\n\n"
        )

    return StreamingResponse(
        _stream_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ----- Historial -------------------------------------------------------------

@router.get("/{session_id}/history", response_model=list[ConversationMessageResponse])
def get_conversation_history(
    session_id: UUID,
    db: Session = Depends(get_db),
):
    session = SessionRepository.get_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return ConversationRepository.list_by_session(db, session_id)
