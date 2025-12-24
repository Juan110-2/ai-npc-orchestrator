from pydantic import BaseModel, Field
from typing import List, Dict, Any
from uuid import UUID
from datetime import datetime

class ScenarioCreate(BaseModel):
    name: str
    context: str
    severity: int = Field(..., ge=1, le=5)
    risk_flags: List[str] = []
    constraints: Dict[str, Any] = {}

class ScenarioResponse(ScenarioCreate):
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True
