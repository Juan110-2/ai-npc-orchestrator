import uuid
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base


class Session(Base):
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False)
    scenario_id = Column(UUID(as_uuid=True), ForeignKey("scenarios.id"), nullable=False)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.user_profiles.id"),
        nullable=True,
    )
    assigned_by = Column(
        UUID(as_uuid=True),
        ForeignKey("public.user_profiles.id"),
        nullable=True,
    )
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())
    current_severity = Column(Float, nullable=False)
    # Severidad real al inicio de la sesión (después de aplicar el límite del perfil).
    # Permite distinguir si la sesión arrancó en el límite máximo/mínimo.
    base_severity = Column(Float, nullable=True)
    status = Column(String(20), nullable=False, default='active', server_default='active')
    accumulated_seconds = Column(Integer, nullable=False, default=0, server_default='0')
    time_source = Column(String(20), nullable=False, default='none', server_default='none')
    last_interaction_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True))
