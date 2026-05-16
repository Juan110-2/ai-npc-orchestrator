from pydantic import BaseModel, Field
from uuid import UUID
from typing import List, Optional
from datetime import datetime

class ConversationInput(BaseModel):
    content: str = Field(
        ...,
        description="Mensaje textual del jugador"
    )
class ConversationResponse(BaseModel):
    reply: str = Field(
        ...,
        description="Respuesta generada por la IA"
    )

class ConversationMessageResponse(BaseModel):
    id: UUID
    session_id: UUID
    role: str
    content: str
    severity: float
    risk_flags: List[str]
    ai_provider: Optional[str]
    tokens_used: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True
