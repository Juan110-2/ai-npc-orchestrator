from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from uuid import UUID
from datetime import datetime

class ScenarioCreate(BaseModel):
    name: str
    context: str
    severity: int = Field(..., ge=1, le=5)
    risk_flags: List[str] = []
    constraints: Dict[str, Any] = {}

class ScenarioUpdate(BaseModel):
    name: Optional[str] = None
    context: Optional[str] = None
    severity: Optional[int] = Field(default=None, ge=1, le=5)
    risk_flags: Optional[List[str]] = None
    constraints: Optional[Dict[str, Any]] = None

class ScenarioResponse(ScenarioCreate):
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True
