import uuid

from pydantic import BaseModel


class MemoryBlockRead(BaseModel):
    scope: str  # user | agent
    owner_id: uuid.UUID
    content: str
    version: int  # 0 = 尚无记忆块


class MemoryBlockWrite(BaseModel):
    scope: str  # user | agent
    agent_id: uuid.UUID | None = None  # scope=="agent" 时必填(须属本人);scope=="user" 忽略
    content: str
