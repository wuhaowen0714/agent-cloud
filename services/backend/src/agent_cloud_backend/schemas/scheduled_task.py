import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ScheduledTaskCreate(BaseModel):
    name: str
    prompt: str
    agent_config_id: uuid.UUID
    schedule_kind: str
    schedule_expr: str
    schedule_tz: str = "Asia/Shanghai"


class ScheduledTaskUpdate(BaseModel):
    name: str | None = None
    prompt: str | None = None
    schedule_kind: str | None = None
    schedule_expr: str | None = None
    schedule_tz: str | None = None
    enabled: bool | None = None


class ScheduledTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    agent_config_id: uuid.UUID
    name: str
    prompt: str
    schedule_kind: str
    schedule_expr: str
    schedule_tz: str
    enabled: bool
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_status: str | None
    last_error: str | None
    last_delivery_error: str | None
    last_run_session_id: uuid.UUID | None
    created_at: datetime
