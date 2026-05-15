from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional


class SessionCreate(BaseModel):
    profile_id: UUID
    scenario_id: UUID
    user_id: Optional[UUID] = None      # estudiante al que se asigna; si None, se usa el caller
    assigned_by: Optional[UUID] = None  # profesor que asigna; si None, se usa el caller


class SessionResponse(BaseModel):
    id: UUID
    profile_id: UUID
    scenario_id: UUID
    user_id: Optional[UUID] = None
    assigned_by: Optional[UUID] = None
    assigned_at: Optional[datetime] = None
    current_severity: int
    started_at: datetime
    ended_at: Optional[datetime] = None

    class Config:
        from_attributes = True
