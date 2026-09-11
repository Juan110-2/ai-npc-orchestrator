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

    # Estado emocional en el momento del turno (rango 0.0–5.0, float para progreso gradual)
    severity = Column(Float, nullable=False)
    risk_flags = Column(JSONB, nullable=False, default=list)

    # Metricas de IA - solo se populan en mensajes del NPC (role="patient")
    ai_provider = Column(Text, nullable=True)
    ai_model = Column(Text, nullable=True)
    tokens_input = Column(Integer, nullable=True)
    tokens_output = Column(Integer, nullable=True)
    tokens_used = Column(Integer, nullable=True)
    latency_ms = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
