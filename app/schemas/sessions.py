from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional

class SessionCreate(BaseModel):
    profile_id: UUID
    scenario_id: UUID

class SessionResponse(BaseModel):
    id: UUID
    profile_id: UUID
    scenario_id: UUID
    current_severity: int
    started_at: datetime
    ended_at: Optional[datetime]

    class Config:
        from_attributes = True
