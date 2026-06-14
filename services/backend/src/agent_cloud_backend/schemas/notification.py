import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    body: str
    origin_session_id: uuid.UUID | None
    created_at: datetime


class MarkDeliveredRequest(BaseModel):
    ids: list[uuid.UUID]
