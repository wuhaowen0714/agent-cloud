import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MessageCreate(BaseModel):
    role: str  # user | assistant | tool
    content: dict
    model: str | None = None
    tokens: int | None = None


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    session_id: uuid.UUID
    seq: int
    role: str
    content: dict
    model: str | None
    tokens: int | None
    created_at: datetime
