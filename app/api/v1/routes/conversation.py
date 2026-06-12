from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.sessions_repository import SessionRepository
from app.schemas.conversation_message import ConversationInput, ConversationMessageResponse
from app.services.conversation import (
    build_stream_inputs,
    commit_patient_message,
    finalize_and_evaluate_sync,
    generate_sync_ai_response,
    persist_patient_message,
    process_turn,
    resolve_session_context,
    stream_response_generator,
    validate_user_input,
)
from app.services.conversation.orchestrator import ConversationOrchestrator

router = APIRouter(prefix="/conversation", tags=["conversation"])


@router.post(
    "/{session_id}",
    response_model=ConversationMessageResponse,
    summary="Enviar mensaje (sincrono)",
    description=(
        "Procesa un turno de conversacion con el personaje simulado (NPC) y devuelve "
        "la respuesta completa cuando esta lista.\n\n"
        "**Flujo interno por turno:**\n"
        "1. Persiste el mensaje del usuario (`role=trainee`).\n"
        "2. En paralelo: clasifica semanticamente el mensaje, evalua la calidad de la "
        "intervencion y detecta reincidencia de abuso (si aplica).\n"
        "3. Recalcula `current_severity` del NPC segun la decision heuristica + impacto del evaluador.\n"
        "4. Detecta condicion de cierre automatico (severidad en limite por N turnos consecutivos "
        "o abuso reiterado).\n"
        "5. Genera la respuesta del NPC via el proveedor de IA activo.\n"
        "6. Persiste el mensaje del NPC (`role=patient`) con severidad, flags y metricas de IA.\n"
        "7. Si la sesion debe cerrarse, la finaliza y dispara la evaluacion automatica.\n\n"
        "Usa `POST /{session_id}/stream` si necesitas respuesta en tiempo real (SSE)."
    ),
    response_description="Mensaje del personaje simulado (NPC) con severidad y metricas de IA.",
    responses={
        400: {"description": "Mensaje vacio o sesion ya cerrada"},
        404: {"description": "Sesion, perfil o escenario no encontrado"},
    },
)
def converse(
    session_id: UUID,
    payload: ConversationInput,
    db: Session = Depends(get_db),
):
    session, profile, scenario = resolve_session_context(session_id, db)
    user_input = validate_user_input(payload.content)
    ctx = process_turn(session, profile, user_input, db)

    ai_response = generate_sync_ai_response(
        session=session,
        profile=profile,
        scenario=scenario,
        user_input=user_input,
        ctx=ctx,
        db=db,
    )
    patient_msg = persist_patient_message(
        db=db,
        session_id=session.id,
        ctx=ctx,
        content=ai_response.content,
        ai_provider=ai_response.provider,
        ai_model=ai_response.model,
        tokens_input=ai_response.tokens_input,
        tokens_output=ai_response.tokens_output,
        tokens_used=ai_response.tokens_total,
        latency_ms=ai_response.latency_ms,
    )
    commit_patient_message(db, session.id)
    finalize_and_evaluate_sync(session, ctx, db)
    return patient_msg


@router.post(
    "/{session_id}/stream",
    summary="Enviar mensaje (streaming SSE)",
    description=(
        "Version streaming de `POST /{session_id}`. "
        "Devuelve la respuesta del personaje simulado en tiempo real mediante "
        "**Server-Sent Events** (`text/event-stream`).\n\n"
        "**Eventos SSE emitidos:**\n\n"
        "| Evento | Payload | Descripcion |\n"
        "|---|---|---|\n"
        "| `chunk` | `{\"chunk\": \"texto...\"}` | Fragmento de texto de la respuesta |\n"
        "| `done` | `{\"done\": true, \"severity\": 2.7, \"should_close\": false, "
        "\"closing_kind\": null, \"metrics\": {...}}` | Fin del stream con metricas |\n"
        "| `error` | `{\"error\": \"mensaje\"}` | Error durante la generacion |\n\n"
        "La logica de heuristica, severidad y cierre automatico es identica al endpoint sincrono."
    ),
    response_description="Stream SSE (`text/event-stream`) con chunks de texto y evento `done` final.",
    responses={
        400: {"description": "Mensaje vacio o sesion ya cerrada"},
        404: {"description": "Sesion, perfil o escenario no encontrado"},
    },
)
def converse_stream(
    session_id: UUID,
    payload: ConversationInput,
    db: Session = Depends(get_db),
):
    session, profile, scenario = resolve_session_context(session_id, db)
    user_input = validate_user_input(payload.content)
    ctx = process_turn(session, profile, user_input, db)
    stream_in = build_stream_inputs(profile, scenario, ctx, user_input)
    context_messages = ConversationOrchestrator._build_context_messages(ctx.context_history)

    return StreamingResponse(
        stream_response_generator(
            session_id=session_id,
            stream_in=stream_in,
            context_messages=context_messages,
            ctx=ctx,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/{session_id}/history",
    response_model=list[ConversationMessageResponse],
    summary="Obtener historial de conversacion",
    description=(
        "Devuelve la transcripcion completa de una sesion, ordenada cronologicamente. "
        "Incluye todos los mensajes del usuario (`role=trainee`) y del personaje simulado "
        "(`role=patient`), con su severidad registrada, flags conductuales y metricas de IA."
    ),
    response_description="Lista completa de mensajes de la sesion en orden cronologico.",
    responses={404: {"description": "Sesion no encontrada"}},
)
def get_conversation_history(
    session_id: UUID,
    db: Session = Depends(get_db),
):
    session = SessionRepository.get_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return ConversationRepository.list_by_session(db, session_id)
