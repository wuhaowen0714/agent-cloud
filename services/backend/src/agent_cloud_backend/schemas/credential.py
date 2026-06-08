import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CredentialCreate(BaseModel):
    name: str
    base_url: str = ""
    api_key: str  # 明文,仅入站;绝不回显


class CredentialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    base_url: str
    masked: str
    created_at: datetime
