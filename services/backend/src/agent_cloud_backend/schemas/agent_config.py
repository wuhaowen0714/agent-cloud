import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AgentConfigCreate(BaseModel):
    name: str
    enabled_tools: list[str] = []
    permissions: dict = {}


class AgentConfigUpdate(BaseModel):
    name: str | None = None
    enabled_tools: list[str] | None = None
    permissions: dict | None = None


class AgentConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    enabled_tools: list[str]
    permissions: dict
    created_at: datetime
    updated_at: datetime
