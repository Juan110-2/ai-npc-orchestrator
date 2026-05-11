import uuid
from sqlalchemy import Column, Text, Integer, Float, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.core.database import Base


class AICallLog(Base):
    """
    Registro tecnico de cada llamada a una API de IA. Persiste latencia,
    tokens, validez de JSON, costo y estado de error.

    Es la fuente UNICA de verdad para la matriz comparativa del Capitulo 3
    del TG (seleccion de API). NO contiene informacion pedagogica del
    estudiante - eso vive en session_evaluations (Capitulo 5).

    Nota: la FK session_id -> sessions(id) ON DELETE SET NULL se enforce a
    nivel de BD (ver migration_002_metrics.sql). NO se declara aqui en
    SQLAlchemy para evitar que el script de bench (que no importa el modelo
    Session) falle con NoReferencedTableError al hacer INSERT.
    """
    __tablename__ = "ai_call_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), nullable=True)

    provider = Column(Text, nullable=False)
    model = Column(Text, nullable=False)
    purpose = Column(Text, nullable=False)
    call_mode = Column(Text, nullable=False, default="sync")
    status = Column(Text, nullable=False)
    error_detail = Column(Text, nullable=True)

    tokens_input = Column(Integer, nullable=True)
    tokens_output = Column(Integer, nullable=True)

    latency_ms = Column(Float, nullable=True)
    ttft_ms = Column(Float, nullable=True)

    json_valid = Column(Boolean, nullable=True)
    response_chars = Column(Integer, nullable=True)
    prompt_chars = Column(Integer, nullable=True)

    cost_usd = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
