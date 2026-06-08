import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ContextDocumentUpsert(BaseModel):
    scope: str  # user | agent
    type: str  # USER | AGENTS | SOUL | IDENTITY | TOOLS | HEARTBEAT | BOOTSTRAP
    agent_id: uuid.UUID | None = None  # scope=="agent" 时必填(须属本人);scope=="user" 忽略
    content: str


class ContextDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    scope: str
    type: str
    owner_id: uuid.UUID
    content: str
    updated_at: datetime
