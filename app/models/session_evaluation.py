import uuid
from sqlalchemy import Column, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from app.core.database import Base


class SessionEvaluation(Base):
    """
    Evaluacion pedagogica por sesion. Una unica fila por session_id.
    Combina dos partes claramente separadas:
      - automatic_metrics: lo calcula el backend al cerrar la sesion.
      - scores + teacher_feedback: lo llena el docente.
    """
    __tablename__ = "session_evaluations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), nullable=False, unique=True)
    student_id = Column(UUID(as_uuid=True), nullable=True)
    evaluator_id = Column(UUID(as_uuid=True), nullable=True)
    rubric_id = Column(UUID(as_uuid=True), nullable=True)

    status = Column(Text, nullable=False, default="draft")  # draft|submitted|reviewed

    automatic_metrics = Column(JSONB, nullable=False, default=dict)
    scores = Column(JSONB, nullable=False, default=dict)
    teacher_feedback = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    submitted_at = Column(DateTime(timezone=True), nullable=True)
