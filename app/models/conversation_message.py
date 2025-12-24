import uuid
from sqlalchemy import Column, Text, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.core.database import Base

class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    role = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    severity = Column(Integer, nullable=False)
    risk_flags = Column(JSONB, nullable=False, default=list)
    ai_provider = Column(Text)
    tokens_used = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
