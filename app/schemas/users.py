from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional, Literal

UserRole = Literal["student", "teacher", "admin"]


class UserProfileResponse(BaseModel):
    id: UUID
    email: str
    full_name: Optional[str] = None
    role: UserRole
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserProfileUpdate(BaseModel):
    role: Optional[UserRole] = None
    full_name: Optional[str] = None
