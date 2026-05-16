from sqlalchemy import Column, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.core.database import Base


class UserProfile(Base):
    """
    Espejo del tabla public.user_profiles de Supabase.
    Se crea automáticamente vía trigger cuando un usuario se registra en auth.users.
    """
    __tablename__ = "user_profiles"
    __table_args__ = {"schema": "public"}

    id         = Column(UUID(as_uuid=True), primary_key=True)
    email      = Column(Text, nullable=False)
    full_name  = Column(Text, nullable=True)
    role       = Column(Text, nullable=False, default="student")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
