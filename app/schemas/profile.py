from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from uuid import UUID
from datetime import datetime


class ProfileBase(BaseModel):
    name: str = Field(..., description="Nombre del paciente simulado")
    description: str = Field(..., description="Descripción del paciente (no clínica real)")
    traits: Dict[str, Any] = Field(default_factory=dict, description="Identidad: edad, personalidad, estilo comunicativo")
    behavior: Dict[str, Any] = Field(default_factory=dict, description="Comportamiento conversacional: triggers, regulators, rango, reacciones")


class ProfileCreate(BaseModel):
    name: str
    description: str
    traits: Dict[str, Any] = Field(default_factory=dict)
    behavior: Dict[str, Any] = Field(default_factory=dict)


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    traits: Optional[Dict[str, Any]] = None
    behavior: Optional[Dict[str, Any]] = None


class ProfileResponse(BaseModel):
    id: UUID
    name: str
    description: str
    traits: Dict[str, Any] = Field(default_factory=dict)
    behavior: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
