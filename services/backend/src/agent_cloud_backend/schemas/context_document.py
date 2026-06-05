import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ContextDocumentUpsert(BaseModel):
    scope: str   # user | agent
    type: str    # USER | AGENTS | SOUL | IDENTITY | TOOLS | HEARTBEAT | BOOTSTRAP
    owner_id: uuid.UUID
    content: str


class ContextDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    scope: str
    type: str
    owner_id: uuid.UUID
    content: str
    updated_at: datetime
