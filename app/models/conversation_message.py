import uuid
from sqlalchemy import Column, Text, Integer, Float, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from app.core.database import Base


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)

    # Rol del emisor: "trainee" (estudiante) | "patient" (NPC)
    role = Column(Text, nullable=False)
    content = Column(Text, nullable=False)

    # Estado emocional en el momento del turno (rango 0–5)
    severity = Column(Integer, nullable=False)
    risk_flags = Column(JSONB, nullable=False, default=list)

    # Métricas de IA �