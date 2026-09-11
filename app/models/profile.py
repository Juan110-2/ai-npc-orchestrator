import uuid
from sqlalchemy import Column, String, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.core.database import Base


class Profile(Base):
    """
    Perfil de NPC simulado.

    Campos JSONB:
      - traits   : identidad del personaje (edad, personalidad, estilo comunicativo, identity_name).
      - behavior : comportamiento conversacional (triggers, regulators, rango severidad, reacciones).
                   Reemplaza a la antigua entidad "protopersona" del frontend.
    """
    __tablename__ = "profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=False)
    traits = Column(JSONB, nullable=False, default=dict)
    behavior = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
