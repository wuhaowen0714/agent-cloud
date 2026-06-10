import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserModelCreate(BaseModel):
    model: str


class UserModelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    model: str
    created_at: datetime
