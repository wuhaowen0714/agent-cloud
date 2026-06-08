import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AgentConfigCreate(BaseModel):
    name: str
    model: str
    provider: str
    thinking_level: str | None = None
    enabled_tools: list[str] = []
    permissions: dict = {}
    key_ref: str | None = None


class AgentConfigUpdate(BaseModel):
    name: str | None = None
    model: str | None = None
    provider: str | None = None
    thinking_level: str | None = None
    enabled_tools: list[str] | None = None
    permissions: dict | None = None
    key_ref: str | None = None


class AgentConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    model: str
    provider: str
    thinking_level: str | None
    enabled_tools: list[str]
    permissions: dict
    key_ref: str | None
    created_at: datetime
    updated_at: datetime
