import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, require_session_access, require_session_owner
from app.core.limiter import limiter
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.conversation_message import ConversationInput, ConversationMessageResponse
from app.services.conversation import (
    build_stream_inputs,
    commit_patient_message,
    finalize_and_evaluate_sync,
    generate_sync_ai_response,
    persist_patient_message,
    process_turn,
    resolve_session_context,
    rollback_turn,
    stream_response_generator,
    validate_user_input,
)
from app.services.conversation.orchestrator import ConversationOrchestrator

logger = logging.getLogger(__name__)

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
        "Si la IA falla (o no se puede guardar la respuesta), el turno se descarta por completo: "
        "se borra el mensaje del usuario (y la respuesta del paciente si llego a guardarse), la "
        "severidad vuelve a su valor previo y se responde `502`; se puede reenviar el mismo mensaje "
        "sin duplicados. Si ademas no se puede confirmar ese descarte se responde `500` y hay que "
        "recargar la conversacion (`GET /{session_id}/history`) antes de reenviar.\n\n"
        "Usa `POST /{session_id}/stream` si necesitas respuesta en tiempo real (SSE).\n\n"
        "Requiere JWT; solo quien realiza la sesion (su dueno) puede escribir turnos: `admin` y el `teacher` que la asigno pueden verla pero no escribir en ella."
    ),
    response_description="Mensaje del personaje simulado (NPC) con severidad y metricas de IA.",
    responses={
        401: {"description": "Token ausente o invalido"},
        403: {"description": "Solo quien realiza la sesion puede escribir en ella (tampoco `admin` ni el `teacher` que la asigno)"},
        400: {"description": "Mensaje vacio o sesion ya cerrada"},
        404: {"description": "Sesion, perfil o escenario no encontrado"},
        500: {"description": "La IA fallo y no se pudo confirmar el descarte del turno; recargar la conversacion antes de reenviar"},
        502: {"description": "La IA fallo; el turno se descarto y se puede reenviar el mensaje"},
    },
)
@limiter.limit("10/minute")
def converse(
    request: Request,
    session_id: UUID,
    payload: ConversationInput,
    db: Session = Depends(get_db),
    _session=Depends(require_session_owner),
):
    session, profile, scenario = resolve_session_context(session_id, db)
    user_input = validate_user_input(payload.content)
    ctx = process_turn(session, profile, user_input, db)

    session_id = session.id
    try:
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
            session_id=session_id,
            ctx=ctx,
            content=ai_response.content,
            ai_provider=ai_response.provider,
            ai_model=ai_response.model,
            tokens_input=ai_response.tokens_input,
            tokens_output=ai_response.tokens_output,
            tokens_used=ai_response.tokens_total,
            latency_ms=ai_response.latency_ms,
        )
        commit_patient_message(db, session_id)
    except Exception:
        # Se descarta el turno completo (mensaje del estudiante y severidad) para
        # que el reintento con el mismo texto no lo duplique. Los ai_call_logs se conservan.
        logger.error("[converse] Fallo la respuesta del paciente (session=%s)", session_id, exc_info=True)
        discarded = rollback_turn(
            db,
            session_id,
            trainee_msg_id=ctx.trainee_msg_id,
            previous_severity=ctx.previous_severity,
        )
        if not discarded:
            raise HTTPException(
                status_code=500,
                detail="No se pudo descartar el turno; recarga la conversacion antes de reenviar.",
            )
        raise HTTPException(
            status_code=502,
            detail="No se pudo generar la respuesta del paciente. El turno se descarto; intenta enviar el mensaje de nuevo.",
        )
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
        "| `error` | `{\"error\": \"mensaje\", \"discarded\": true}` | Error durante la generacion. "
        "`discarded: true` indica que el turno se descarto (se borra el mensaje del usuario, la "
        "severidad vuelve a su valor previo y no se guarda respuesta parcial): se puede reenviar el "
        "mismo mensaje sin duplicados. `discarded: false` indica que no se pudo confirmar el descarte: "
        "hay que recargar la conversacion (`GET /{session_id}/history`) antes de reenviar |\n\n"
        "La logica de heuristica, severidad y cierre automatico es identica al endpoint sincrono.\n\n"
        "Requiere JWT; solo quien realiza la sesion (su dueno) puede escribir turnos: `admin` y el `teacher` que la asigno pueden verla pero no escribir en ella."
    ),
    response_description="Stream SSE (`text/event-stream`) con chunks de texto y evento `done` final.",
    responses={
        401: {"description": "Token ausente o invalido"},
        403: {"description": "Solo quien realiza la sesion puede escribir en ella (tampoco `admin` ni el `teacher` que la asigno)"},
        400: {"description": "Mensaje vacio o sesion ya cerrada"},
        404: {"description": "Sesion, perfil o escenario no encontrado"},
    },
)
@limiter.limit("10/minute")
def converse_stream(
    request: Request,
    session_id: UUID,
    payload: ConversationInput,
    db: Session = Depends(get_db),
    _session=Depends(require_session_owner),
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
        "(`role=patient`), con su severidad registrada, flags conductuales y metricas de IA. "
        "Requiere ser el dueno de la sesion, `admin` o el `teacher` que la asigno."
    ),
    response_description="Lista completa de mensajes de la sesion en orden cronologico.",
    responses={
        401: {"description": "Token ausente o invalido"},
        403: {"description": "La sesion no es del usuario, ni la asigno (`teacher`), y no es `admin`"},
        404: {"description": "Sesion no encontrada"},
    },
)
def get_conversation_history(
    session_id: UUID,
    db: Session = Depends(get_db),
    _session=Depends(require_session_access),
):
    return ConversationRepository.list_by_session(db, session_id)
