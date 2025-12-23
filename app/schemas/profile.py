from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Dict, Any
from uuid import UUID
from datetime import datetime

class ProfileBase(BaseModel):
    name: str = Field(..., description="Nombre del caso o paciente simulado")
    description: str = Field(..., description="Descripción del caso o paciente simulado (no clínica real)")
    traits: Dict[str, Any] = Field(..., description="Características del caso o paciente simulado")

class ProfileCreate(BaseModel):
    name: str
    description: str
    traits: Dict[str, Any]

class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    traits: Optional[Dict[str, Any]] = None

class ProfileResponse(ProfileCreate):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True