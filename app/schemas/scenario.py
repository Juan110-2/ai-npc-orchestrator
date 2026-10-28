from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

_CONTEXT_EXAMPLE = (
    "El personaje acude por primera vez a una conversación de apoyo. Refiere estrés intenso "
    "por presión laboral y dificultad para dormir desde hace tres meses. Teme perder su empleo "
    "y siente que no puede hablar del tema con su familia."
)


class ScenarioCreate(BaseModel):
    name: str = Field(
        ...,
        description="Nombre identificador del escenario de simulación.",
        examples=["Primera conversación: estrés laboral"],
    )
    context: str = Field(
        ...,
        description=(
            "Descripción narrativa de la situación. "
            "El NPC la recibe como contexto interno para construir sus respuestas. "
            "Debe ser suficientemente detallada para guiar respuestas coherentes."
        ),
        examples=[_CONTEXT_EXAMPLE],
    )
    severity: int = Field(
        ...,
        ge=1,
        le=5,
        description=(
            "Severidad emocional inicial del personaje simulado al comenzar la sesión "
            "(1 = leve, 5 = muy alta). "
            "El motor de conversación parte de este valor y lo ajusta dinámicamente."
        ),
        examples=[3],
    )
    risk_flags: List[str] = Field(
        default=[],
        description=(
            "Indicadores de riesgo presentes en el escenario. "
            "Son un rasgo permanente del personaje: se inyectan como contexto en el prompt "
            "('Indicadores presentes: ...'), no en la lógica de cierre automático de la sesión."
        ),
        examples=[["ideación_pasiva", "aislamiento_social"]],
    )
    constraints: Dict[str, Any] = Field(
        default={},
        description=(
            "Restricciones de comportamiento específicas del escenario. "
            "Pueden incluir temas prohibidos, límites de turnos o instrucciones adicionales para el NPC."
        ),
        examples=[{"forbidden_topics": ["trabajo pasado"], "max_turns_before_escalation": 8}],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Primera conversación: estrés laboral",
                "context": _CONTEXT_EXAMPLE,
                "severity": 3,
                "risk_flags": ["ideación_pasiva"],
                "constraints": {},
            }
        }
    }


class ScenarioUpdate(BaseModel):
    name: Optional[str] = Field(
        None,
        description="Nuevo nombre del escenario.",
        examples=["Primera conversación: estrés laboral (rev. 2)"],
    )
    context: Optional[str] = Field(
        None,
        description="Nueva descripción narrativa de la situación.",
    )
    severity: Optional[int] = Field(
        default=None,
        ge=1,
        le=5,
        description="Nueva severidad inicial (1 a 5).",
        examples=[2],
    )
    risk_flags: Optional[List[str]] = Field(
        None,
        description="Nueva lista de indicadores de riesgo. Reemplaza la lista existente.",
    )
    constraints: Optional[Dict[str, Any]] = Field(
        None,
        description="Nuevo objeto de restricciones. Reemplaza el existente.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "severity": 2,
                "risk_flags": [],
            }
        }
    }


class ScenarioResponse(ScenarioCreate):
    id: UUID = Field(..., description="Identificador único del escenario.")
    created_at: datetime = Field(..., description="Fecha y hora de creación (UTC).")
    created_by: Optional[UUID] = Field(
        None,
        description=(
            "Docente que creó el escenario. Solo él o un `admin` pueden editarlo o eliminarlo; "
            "si es `null`, solo un `admin`."
        ),
    )

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
                "name": "Primera conversación: estrés laboral",
                "context": _CONTEXT_EXAMPLE,
                "severity": 3,
                "risk_flags": ["ideación_pasiva"],
                "constraints": {},
                "created_at": "2025-05-01T10:00:00Z",
                "created_by": "c3d4e5f6-a7b8-9012-cdef-123456789012",
            }
        },
    }
