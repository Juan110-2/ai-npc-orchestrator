from __future__ import annotations

import json
import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.services.conversation.constants import MAX_CLOSING_TURNS, MAX_RESPONSE_CHARS
from app.services.conversation.core import (
    commit_with_rollback,
    finalize_session_in_generator,
    persist_patient_message,
    run_auto_evaluation_safely,
)
from app.services.conversation.models import StreamExecutionState, StreamInputs, TurnContext
from app.services.conversation.orchestrator import ConversationOrchestrator

logger = logging.getLogger(__name__)


def safe_accumulate(current: str, chunk: str) -> str:
    remaining = MAX_RESPONSE_CHARS - len(current)
    if remaining <= 0:
        return current
    return current + chunk[:remaining]


def build_stream_inputs(profile, scenario, ctx: TurnContext, user_input: str) -> StreamInputs:
    if ctx.should_close:
        # Turno final: prompt NORMAL, sin instruccion de despedida (el LLM la
        # ignora casi siempre, ver ConversationOrchestrator._CLOSING_TAILS). La
        # cola de cierre garantizada se agrega despues de que termine el stream,
        # en stream_response_generator.
        system_prompt, _ = ConversationOrchestrator.build_prompt(
            profile=profile,
            scenario=scenario,
            current_severity=ctx.final_severity,
            response_mode=ctx.decision.response_mode.value,
            max_sentences=ctx.decision.max_sentences,
            should_rotate_focus=ctx.decision.should_rotate_focus,
        )
        return StreamInputs(
            system_prompt=system_prompt,
            effective_user_input=user_input,
            forced_text=None,
        )

    if ctx.closing is not None:
        turns_left = MAX_CLOSING_TURNS - ctx.closing["patient_turns"]
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
    )
    return StreamInputs(
        system_prompt=system_prompt,
        effective_user_input=user_input,
        forced_text=None,
    )


def yield_chunk_event(chunk: str) -> str:
    return f"event: chunk\ndata: {json.dumps({'chunk': chunk})}\n\n"


def yield_error_event(message: str) -> str:
    return f"event: error\ndata: {json.dumps({'error': message})}\n\n"


def yield_done_event(ctx: TurnContext, state: StreamExecutionState) -> str:
    return (
        "event: done\ndata: "
        + json.dumps(
            {
                "done": True,
                "severity": ctx.final_severity,
                "should_close": ctx.should_close,
                "closing_kind": ctx.closing_kind,
                "metrics": {
                    "provider": state.provider,
                    "model": state.model,
                    "tokens_input": state.tokens_input,
                    "tokens_output": state.tokens_output,
                    "latency_ms": state.latency_ms,
                    "ttft_ms": state.ttft_ms,
                },
            }
        )
        + "\n\n"
    )


def iter_forced_stream(forced_text: str, state: StreamExecutionState):
    state.provider = "deterministic"
    state.model = "fallback"
    for word in forced_text.split():
        chunk = word + " "
        state.accumulated = safe_accumulate(state.accumulated, chunk)
        yield yield_chunk_event(chunk)


def iter_ai_stream(
    *,
    gen_db: Session,
    session_id: UUID,
    stream_in: StreamInputs,
    context_messages,
    state: StreamExecutionState,
):
    from app.services.ai.base import StreamResult
    from app.services.ai.metrics_logger import log_ai_call

    with log_ai_call(
        gen_db,
        purpose="orchestrator",
        session_id=session_id,
        call_mode="stream",
    ) as log_ctx:
        prompt_len = len(stream_in.system_prompt or "") + len(stream_in.effective_user_input)
        log_ctx.record_prompt_chars(prompt_len)
        generator = log_ctx.client.generate_stream(
            stream_in.system_prompt,
            stream_in.effective_user_input,
            context_messages,
        )
        stream_result: StreamResult | None = None
        try:
            while True:
                chunk = next(generator)
                state.accumulated = safe_accumulate(state.accumulated, chunk)
                yield yield_chunk_event(chunk)
        except StopIteration as stop:
            if isinstance(stop.value, StreamResult):
                stream_result = stop.value
        except Exception as exc:
            state.stream_error = exc
            logger.error("[converse_stream] Error en generate_stream", exc_info=True)

        state.provider = log_ctx.client.provider
        state.model = log_ctx.client.model
        if stream_result is not None:
            state.tokens_input = stream_result.tokens_input
            state.tokens_output = stream_result.tokens_output
            state.latency_ms = stream_result.latency_ms
            state.ttft_ms = stream_result.ttft_ms
            log_ctx.record_stream_result(stream_result, state.accumulated)
        elif state.stream_error is not None:
            log_ctx.record_error(state.stream_error)


def persist_stream_message(
    *,
    gen_db: Session,
    session_id: UUID,
    ctx: TurnContext,
    state: StreamExecutionState,
) -> None:
    persist_patient_message(
        db=gen_db,
        session_id=session_id,
        ctx=ctx,
        content=state.accumulated.strip(),
        ai_provider=state.provider,
        ai_model=state.model,
        tokens_input=state.tokens_input,
        tokens_output=state.tokens_output,
        tokens_used=state.tokens_input + state.tokens_output,
        latency_ms=state.latency_ms,
    )


def handle_stream_error_persistence(
    *,
    gen_db: Session,
    session_id: UUID,
    ctx: TurnContext,
    state: StreamExecutionState,
) -> None:
    if not state.accumulated.strip():
        return
    try:
        persist_stream_message(
            gen_db=gen_db,
            session_id=session_id,
            ctx=ctx,
            state=state,
        )
        commit_with_rollback(
            gen_db,
            "[converse_stream] Fallo persistencia del parcial tras error (session=%s)",
            session_id,
            reraise=True,
        )
    except Exception:
        logger.error("[converse_stream] Fallo persistencia del parcial tras error", exc_info=True)


def commit_stream_message(
    *,
    gen_db: Session,
    session_id: UUID,
    ctx: TurnContext,
    state: StreamExecutionState,
) -> bool:
    try:
        persist_stream_message(
            gen_db=gen_db,
            session_id=session_id,
            ctx=ctx,
            state=state,
        )
        return commit_with_rollback(
            gen_db,
            "[converse_stream] Fallo commit del patient_msg (session=%s)",
            session_id,
        )
    except Exception:
        logger.error("[converse_stream] Fallo commit del patient_msg", exc_info=True)
        return False


def finalize_and_evaluate_stream(gen_db: Session, session_id: UUID, ctx: TurnContext) -> None:
    if not ctx.should_close:
        return
    finalize_session_in_generator(gen_db, session_id, ctx)
    run_auto_evaluation_safely(gen_db, session_id, "converse_stream")


def stream_response_generator(
    *,
    session_id: UUID,
    stream_in: StreamInputs,
    context_messages,
    ctx: TurnContext,
):
    gen_db = SessionLocal()
    try:
        state = StreamExecutionState()
        if stream_in.forced_text:
            yield from iter_forced_stream(stream_in.forced_text, state)
        else:
            yield from iter_ai_stream(
                gen_db=gen_db,
                session_id=session_id,
                stream_in=stream_in,
                context_messages=context_messages,
                state=state,
            )

        if state.stream_error is not None:
            yield yield_error_event(str(state.stream_error))
            handle_stream_error_persistence(
                gen_db=gen_db,
                session_id=session_id,
                ctx=ctx,
                state=state,
            )
            return

        if ctx.should_close:
            # Cola de cierre garantizada (ver _CLOSING_TAILS): se emite como un
            # chunk mas, en vivo, y se agrega tambien a lo que se va a guardar --
            # asi lo que ve el estudiante en pantalla y lo que queda en la base
            # de datos coinciden.
            tail_suffix = ConversationOrchestrator.closing_tail_suffix(
                state.accumulated, ctx.closing_kind
            )
            if tail_suffix:
                state.accumulated = safe_accumulate(state.accumulated, tail_suffix)
                yield yield_chunk_event(tail_suffix)

        if not commit_stream_message(
            gen_db=gen_db,
            session_id=session_id,
            ctx=ctx,
            state=state,
        ):
            yield yield_error_event("DB commit failed")
            return

        finalize_and_evaluate_stream(gen_db, session_id, ctx)
        yield yield_done_event(ctx, state)
    finally:
        gen_db.close()
