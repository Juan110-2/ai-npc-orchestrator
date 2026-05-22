from pydantic import BaseModel, Field
from uuid import UUID
from typing import List, Optional
from datetime import datetime


class ConversationInput(BaseModel):
    content: str = Field(
        ...,
        description=(
            "Mensaje textual del usuario dirigido al personaje simulado (NPC). "
            "No puede ser vacío ni contener solo espacios en blanco."
        ),
        examples=["Hola María, cuéntame qué te trajo aquí hoy."],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "content": "Hola María, cuéntame qué te trajo aquí hoy.",
            }
        }
    }


class ConversationResponse(BaseModel):
    reply: str = Field(
        ...,
        description="Respuesta generada por la IA en nombre del personaje simulado (NPC).",
    )


class ConversationMessageResponse(BaseModel):
    id: UUID = Field(..., description="Identificador único del mensaje.")
    session_id: UUID = Field(..., description="UUID de la sesión a la que pertenece este mensaje.")
    role: str = Field(
        ...,
        description=(
            "Rol del emisor: "
            "`trainee` (el usuario que practica) o `patient` (el personaje simulado / NPC)."
        ),
        examples=["patient"],
    )
    content: str = Field(..., description="Texto completo del mensaje.")
    severity: float = Field(
        ...,
        description=(
            "Severidad emocional del NPC en el momento en que se generó este mensaje, "
            "dentro del rango `behavior_min`–`behavior_max` del perfil."
        ),
        examples=[2.7],
    )
    risk_flags: List[str] = Field(
        ...,
        description=(
            "Indicadores conductuales detectados en este turno. "
            "Posibles valores: `abuse` (lenguaje inapropiado), "
            "`repeat_abuse` (reincidencia de abuso), `risk` (indicador de riesgo)."
        ),
        examples=[[]],
    )
    ai_provider: Optional[str] = Field(
        None,
        description=(
            "Proveedor de IA que generó la respuesta "
            "(p. ej. `openai`, `gemini`, `deepseek`). "
            "`null` para mensajes del usuario (`trainee`)."
        ),
        examples=["openai"],
    )
    tokens_used: Optional[int] = Field(
        None,
        description=(
            "Total de tokens consumidos (entrada + salida) en esta llamada a la IA. "
            "`null` para mensajes del usuario (`trainee`)."
        ),
        examples=[312],
    )
    created_at: datetime = Field(..., description="Fecha y hora de creación del mensaje (UTC).")

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "id": "e5f6a7b8-c9d0-1234-efab-345678901234",
                "session_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
                "role": "patient",
                "content": "No sé por dónde empezar... últimamente siento que todo se me viene encima.",
                "severity": 2.7,
                "risk_flags": [],
                "ai_provider": "openai",
                "tokens_used": 312,
                "created_at": "2025-05-10T09:01:45Z",
            }
        },
    }
