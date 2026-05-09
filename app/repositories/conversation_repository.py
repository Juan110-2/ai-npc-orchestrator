from sqlalchemy.orm import Session

from app.models.conversation_message import ConversationMessage


class ConversationRepository:

    @staticmethod
    def add(
        db: Session,
        session_id,
        role: str,
        content: str,
        severity: int,
        risk_flags: list,
        # Métricas de IA — solo se envían para mensajes del paciente
        ai_provider: str | None = None,
        ai_model: str | None = None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
        tokens_used: int | None = None,
        latency_ms: float | None = None,
    ) -> ConversationMessage:
        msg = ConversationMessage(
            session_id=session_id,
            role=role,
            content=content,
            severity=severity,
            risk_flags=risk_flags,
            ai_provider=ai_provider,
            ai_model=ai_model,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)
        return msg

    @staticmethod
    def list_by_session(db: Session, session_id) -> list[ConversationMessage]:
        return (
            db.query(ConversationMessage)
            .filter(ConversationMessage.session_id == session_id)
            .order_by(ConversationMessage.created_at.asc()