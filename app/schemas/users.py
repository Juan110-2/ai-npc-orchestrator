from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

UserRole = Literal["student", "teacher", "admin"]


class UserProfileResponse(BaseModel):
    id: UUID = Field(..., description="Identificador único del usuario (mismo UUID que en Supabase Auth).")
    email: str = Field(..., description="Dirección de correo electrónico del usuario.")
    full_name: Optional[str] = Field(None, description="Nombre completo del usuario.")
    role: UserRole = Field(
        ...,
        description=(
            "Rol del usuario en la plataforma: "
            "`student` (realiza sesiones), "
            "`teacher` (asigna sesiones y evalúa), "
            "`admin` (acceso total)."
        ),
        examples=["student"],
    )
    created_at: datetime = Field(..., description="Fecha y hora de registro (UTC).")
    updated_at: datetime = Field(..., description="Fecha y hora de última modificación (UTC).")

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "id": "d4e5f6a7-b8c9-0123-defa-234567890123",
                "email": "ana.martinez@universidad.edu",
                "full_name": "Ana Martínez",
                "role": "student",
                "created_at": "2025-04-01T08:00:00Z",
                "updated_at": "2025-04-01T08:00:00Z",
            }
        },
    }


class UserProfileUpdate(BaseModel):
    role: Optional[UserRole] = Field(
        None,
        description="Nuevo rol del usuario (`student`, `teacher` o `admin`).",
        examples=["teacher"],
    )
    full_name: Optional[str] = Field(
        None,
        description="Nuevo nombre completo del usuario.",
        examples=["Ana Martínez"],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "role": "teacher",
                "full_name": "Ana Martínez",
            }
        }
    }
