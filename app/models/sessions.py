import uuid
from sqlalchemy import Column, DateTime, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base


class Session(Base):
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False)
    scenario_id = Column(UUID(as_uuid=True), ForeignKey("scenarios.id"), nullable=False)
    # Estudiante propietario de la sesion. Puede ser NULL si la sesion se crea
    # sin auth activo (modo desarrollo). FK a public.user_profiles.id.
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.user_profiles.id"),
        nullable=True,
    )
    current_severity = Column(Integer, nullable=False)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True))
