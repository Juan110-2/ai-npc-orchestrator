from pydantic import BaseModel, Field


class CatalogUsageResponse(BaseModel):
    """Uso de un perfil o escenario por parte de las sesiones, para decidir si se puede eliminar."""

    total_sessions: int = Field(
        ...,
        description="Total de sesiones que referencian el perfil o escenario.",
        examples=[3],
    )
    sessions_with_activity: int = Field(
        ...,
        description=(
            "Sesiones con actividad registrada: tienen al menos un mensaje de conversación, "
            "una evaluación o un registro de llamada a IA."
        ),
        examples=[1],
    )
    unused_sessions: int = Field(
        ...,
        description=(
            "Sesiones sin uso (asignadas o creadas pero sin mensajes, evaluación ni registros de IA). "
            "Se borran junto con el perfil o escenario al eliminarlo."
        ),
        examples=[2],
    )
    can_delete: bool = Field(
        ...,
        description="`true` si no hay sesiones con actividad (`sessions_with_activity == 0`).",
        examples=[False],
    )
    allowed: bool = Field(
        ...,
        description=(
            "`true` si el usuario autenticado puede eliminarlo: es su autor (`created_by`) o `admin`. "
            "Los casos sin autor registrado solo los elimina un `admin`."
        ),
        examples=[True],
    )
