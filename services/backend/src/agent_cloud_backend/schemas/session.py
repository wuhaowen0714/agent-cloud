import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SessionCreate(BaseModel):
    agent_config_id: uuid.UUID
    title: str | None = None


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    agent_config_id: uuid.UUID
    title: str | None
    status: str
    work_subdir: str
    created_at: datetime
    last_active_at: datetime
    last_context_tokens: int | None = None
