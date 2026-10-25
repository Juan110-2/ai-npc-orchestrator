import uuid
from sqlalchemy import Column, Text, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.core.database import Base

class Scenario(Base):
    __tablename__ = "scenarios"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    context = Column(Text, nullable=False)
    severity = Column(Integer, nullable=False)
    risk_flags = Column(JSONB, nullable=False, default=list)
    constraints = Column(JSONB, nullable=False, default=dict)
    # Docente que creó el escenario. No restringe el acceso: los casos son compartidos.
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
