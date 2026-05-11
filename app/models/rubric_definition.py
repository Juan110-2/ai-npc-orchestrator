import uuid
from sqlalchemy import Column, Text, Integer, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from app.core.database import Base


class RubricDefinition(Base):
    """
    Rubrica versionada para evaluar sesiones de practica clinica simulada.
    Cada cambio en la rubrica crea una nueva fila (version+1). Asi una
    evaluacion vieja siempre puede recuperar la rubrica con la que fue calificada.
    """
    __tablename__ = "rubric_definitions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version = Column(Integer, nullable=False)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    criteria = Column(JSONB, nullable=False)  # array de {key, label, max_score, weight, description}
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
