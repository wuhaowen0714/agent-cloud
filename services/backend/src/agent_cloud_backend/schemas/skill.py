import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    description: str
    source: str
    version: str
    requires: dict
    package_ref: str
    created_at: datetime


class SkillInstallRequest(BaseModel):
    name: str  # 内置 registry 中的 skill 名


class SkillInstallFromWorkspaceRequest(BaseModel):
    path: str  # 工作区内含 SKILL.md 的目录(相对工作区根,如 "myskill")


class AgentSkillsUpdate(BaseModel):
    skill_ids: list[uuid.UUID]
