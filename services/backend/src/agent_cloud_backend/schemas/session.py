import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SessionCreate(BaseModel):
    agent_config_id: uuid.UUID
    title: str | None = None
    model: str | None = None  # 留空 → 平台默认模型
    credential_id: uuid.UUID | None = None  # None = 平台 sophnet 全局 key


class SessionUpdate(BaseModel):
    # 全可选;PATCH 按 model_dump(exclude_unset=True) 只改提供的字段。credential_id 显式传 null
    # = 切回平台 sophnet。
    title: str | None = None
    model: str | None = None
    credential_id: uuid.UUID | None = None


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    agent_config_id: uuid.UUID
    model: str
    credential_id: uuid.UUID | None = None
    title: str | None
    status: str
    work_subdir: str
    created_at: datetime
    last_active_at: datetime
    last_context_tokens: int | None = None


class RollbackRequest(BaseModel):
    message_id: uuid.UUID


class RollbackResult(BaseModel):
    deleted_count: int
    user_text: str


class ForkRequest(BaseModel):
    message_id: uuid.UUID


class ForkResult(BaseModel):
    new_session_id: uuid.UUID
    user_text: str
