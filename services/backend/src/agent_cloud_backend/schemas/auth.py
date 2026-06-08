from pydantic import BaseModel, EmailStr, Field

from agent_cloud_backend.schemas.user import UserRead


class RegisterBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    user: UserRead
