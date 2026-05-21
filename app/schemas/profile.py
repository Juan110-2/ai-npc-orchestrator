from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from uuid import UUID
from datetime import datetime

_TRAITS_EXAMPLE = {
    "age": 34,
    "gender": "femenino",
    "personality": "ansioso",
    "communication_style": "verborrágico",
    "occupation": "contadora",
}

_BEHAVIOR_EXAMPLE = {
    "behavior_min": 1.0,
    "behavior_max": 4.5,
    "triggers": ["invalidación", "impaciencia", "interrupciones"],
    "regulators": ["escucha activa", "validación emocional", "reformulación empática"],
}


class ProfileCreate(BaseModel):
    name: str = Field(
        ...,
        description="Nombre del NPC, usado como identificador legible.",
        examples=["María García"],
    )
    description: str = Field(
        ...,
        description=(
            "Descripción narrativa breve del NPC. "
            "Contexto visible para el orquestador al construir el personaje."
        ),
        examples=["Mujer de 34 años con alta carga emocional y tendencia a la catastrofización."],
    )
    traits: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Identidad del NPC: edad, género, personalidad, estilo comunicativo, ocupación, etc. "
            "Estos valores informan el prompt de generación de respuestas."
        ),
        examples=[_TRAITS_EXAMPLE],
    )
    behavior: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Comportamiento conversacional: `behavior_min`/`behavior_max` definen el rango de "
            "severidad emocional permitido (0–5). `triggers` suben severidad; `regulators` la bajan."
        ),
        examples=[_BEHAVIOR_EXAMPLE],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "María García",
                "description": "Mujer de 34 años con alta carga emocional y tendencia a la catastrofización.",
                "traits": _TRAITS_EXAMPLE,
                "behavior": _BEHAVIOR_EXAMPLE,
            }
        }
    }


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(
        None,
        description="Nuevo nombre del NPC.",
        examples=["María García (rev. 2)"],
    )
    description: Optional[str] = Field(
        None,
        description="Nueva descripción narrativa del NPC.",
    )
    traits: Optional[Dict[str, Any]] = Field(
        None,
        description="Reemplazo completo del objeto `traits`. Los campos omitidos no se conservan.",
    )
    behavior: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Reemplazo completo del objeto `behavior`. "
            "Incluye `behavior_min`, `behavior_max`, `triggers` y `regulators`."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "behavior": {
                    "behavior_min": 0.5,
                    "behavior_max": 5.0,
                    "triggers": ["invalidación"],
                    "regulators": ["escucha activa"],
                }
            }
        }
    }


class ProfileResponse(BaseModel):
    id: UUID = Field(..., description="Identificador único del perfil.")
    name: str = Field(..., description="Nombre del NPC.")
    description: str = Field(..., description="Descripción narrativa del NPC.")
    traits: Dict[str, Any] = Field(
        default_factory=dict,
        description="Identidad del NPC: edad, género, personalidad, estilo comunicativo.",
    )
    behavior: Dict[str, Any] = Field(
        default_factory=dict,
        description="Comportamiento conversacional y rango de severidad emocional.",
    )
    created_at: datetime = Field(..., description="Fecha y hora de creación (UTC).")
    updated_at: datetime = Field(..., description="Fecha y hora de última modificación (UTC).")

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "name": "María García",
                "description": "Mujer de 34 años con alta carga emocional y tendencia a la catastrofización.",
                "traits": _TRAITS_EXAMPLE,
                "behavior": _BEHAVIOR_EXAMPLE,
                "created_at": "2025-05-01T10:00:00Z",
                "updated_at": "2025-05-01T10:00:00Z",
            }
        },
    }
