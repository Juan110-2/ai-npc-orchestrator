from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

_SESSION_ID_EX = "c3d4e5f6-a7b8-9012-cdef-123456789012"
_PROFILE_ID_EX = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
_SCENARIO_ID_EX = "b2c3d4e5-f6a7-8901-bcde-f12345678901"
_USER_ID_EX = "d4e5f6a7-b8c9-0123-defa-234567890123"


class SessionCreate(BaseModel):
    profile_id: UUID = Field(
        ...,
        description="UUID del perfil del personaje simulado (NPC) que se usará en esta sesión.",
        examples=[_PROFILE_ID_EX],
    )
    scenario_id: UUID = Field(
        ...,
        description="UUID del escenario que contextualiza la sesión.",
        examples=[_SCENARIO_ID_EX],
    )
    user_id: Optional[UUID] = Field(
        None,
        description=(
            "UUID del usuario que realizará la sesión; debe existir en `user_profiles`. "
            "Si se omite, se toma automáticamente del JWT del caller."
        ),
        examples=[None],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "profile_id": _PROFILE_ID_EX,
                "scenario_id": _SCENARIO_ID_EX,
                "user_id": None,
            }
        }
    }


class SessionResponse(BaseModel):
    id: UUID = Field(..., description="Identificador único de la sesión.")
    profile_id: UUID = Field(..., description="UUID del perfil del personaje simulado (NPC).")
    scenario_id: UUID = Field(..., description="UUID del escenario de la sesión.")
    user_id: Optional[UUID] = Field(None, description="UUID del usuario que realiza la sesión.")
    assigned_by: Optional[UUID] = Field(None, description="UUID de quien asignó la sesión.")
    assigned_at: Optional[datetime] = Field(None, description="Fecha y hora de asignación (UTC).")
    status: str = Field(
        "active",
        description=(
            "Estado de la sesión: "
            "`active` (en curso), "
            "`completed` (cierre exitoso o manual), "
            "`terminated` (cierre por crisis o comportamiento inapropiado)."
        ),
        examples=["active"],
    )
    accumulated_seconds: int = Field(
        0,
        description="Tiempo de práctica acumulado en segundos, reportado por el frontend vía `/time`.",
        examples=[180],
    )
    time_source: str = Field(
        "none",
        description=(
            "Origen del tiempo acumulado: "
            "`none` (sin reporte aún), `explicit` (reportado por el frontend)."
        ),
        examples=["explicit"],
    )
    last_interaction_at: Optional[datetime] = Field(
        None,
        description="Fecha y hora de la última interacción registrada (UTC).",
    )
    current_severity: float = Field(
        ...,
        description=(
            "Severidad emocional actual del NPC dentro del rango `behavior_min` a `behavior_max`. "
            "Se actualiza automáticamente en cada turno de conversación."
        ),
        examples=[2.7],
    )
    base_severity: Optional[float] = Field(
        None,
        description="Severidad inicial al comenzar la sesión (valor de referencia).",
        examples=[3.0],
    )
    started_at: datetime = Field(..., description="Fecha y hora de inicio (UTC).")
    ended_at: Optional[datetime] = Field(
        None,
        description="Fecha y hora de cierre (UTC). `null` si la sesión sigue activa.",
    )
    last_ai_model: Optional[str] = Field(
        None,
        description="Último modelo de IA usado en esta sesión, obtenido desde `ai_call_logs`.",
    )

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "id": _SESSION_ID_EX,
                "profile_id": _PROFILE_ID_EX,
                "scenario_id": _SCENARIO_ID_EX,
                "user_id": _USER_ID_EX,
                "assigned_by": _USER_ID_EX,
                "assigned_at": "2025-05-10T09:00:00Z",
                "status": "active",
                "accumulated_seconds": 180,
                "time_source": "explicit",
                "last_interaction_at": "2025-05-10T09:03:00Z",
                "current_severity": 2.7,
                "base_severity": 3.0,
                "started_at": "2025-05-10T09:00:00Z",
                "ended_at": None,
                "last_ai_model": "gpt-4o-mini",
            }
        },
    }


class PaginatedSessionsResponse(BaseModel):
    items: list[SessionResponse] = Field(..., description="Lista de sesiones de la página actual.")
    total: int = Field(..., description="Total de sesiones que coinciden con los filtros aplicados.")
    page: int = Field(..., description="Número de la página actual (base 1).")
    pages: int = Field(..., description="Total de páginas disponibles.")
    limit: int = Field(..., description="Máximo de ítems por página.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "items": [],
                "total": 0,
                "page": 1,
                "pages": 1,
                "limit": 20,
            }
        }
    }
