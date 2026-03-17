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
        ai_provider: str = None,
        tokens_used: int = None
    ):
        msg = ConversationMessage(
            session_id=session_id,
            role=role,
            content=content,
            severity=severity,
            risk_flags=risk_flags,
            ai_provider=ai_provider,
            tokens_used=tokens_used
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)
        return msg

    @staticmethod
    def list_by_session(db: Session, session_id):
        return (
            db.query(ConversationMessage)
            .filter(ConversationMessage.session_id == session_id)
            .order_by(ConversationMessage.created_at.asc())
            .all()
        )

    @staticmethod
    def list_recent_by_session(db: Session, session_id, limit: int = 12):
        rows = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.session_id == session_id)
            .order_by(ConversationMessage.created_at.desc())
            .limit(limit)
            .all()
        )
        return list(reversed(rows))
