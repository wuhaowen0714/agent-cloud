import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MemoryAppend(BaseModel):
    scope: str  # user | agent
    agent_id: uuid.UUID | None = None  # scope=="agent" 时必填(须属本人);scope=="user" 忽略
    content: str
    source_session_id: uuid.UUID | None = None


class MemoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    scope: str
    owner_id: uuid.UUID
    content: str
    source_session_id: uuid.UUID | None
    created_at: datetime
