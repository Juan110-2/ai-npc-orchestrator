from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional


class SessionCreate(BaseModel):
    profile_id: UUID
    scenario_id: UUID
    user_id: Optional[UUID] = None  # se puede pasar explícitamente o extraer del JWT


class SessionResponse(BaseModel):
    id: UUID
    profile_id: UUID
    scenario_id: UUID
    user_id: Optional[UUID] = None
    current_severity: int
    started_at: datetime
    ended_at: Optional[datetime] = None

    class Config:
        from_attributes = True
