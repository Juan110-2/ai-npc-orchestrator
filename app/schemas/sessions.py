from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional


class SessionCreate(BaseModel):
    profile_id: UUID
    scenario_id: UUID
    user_id: Optional[UUID] = None
    assigned_by: Optional[UUID] = None


class SessionResponse(BaseModel):
    id: UUID
    profile_id: UUID
    scenario_id: UUID
    user_id: Optional[UUID] = None
    assigned_by: Optional[UUID] = None
    assigned_at: Optional[datetime] = None
    status: str = 'active'
    accumulated_seconds: int = 0
    time_source: str = 'none'
    last_interaction_at: Optional[datetime] = None
    current_severity: float
    base_severity: Optional[float] = None
    started_at: datetime
    ended_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PaginatedSessionsResponse(BaseModel):
    items: list[SessionResponse]
    total: int
    page: int
    pages: int
    limit: int
