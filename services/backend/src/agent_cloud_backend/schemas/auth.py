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
    # 移动端用:存安全存储(Keychain/Keystore),刷新时回传 body。Web 走 httponly cookie、忽略此字段。
    refresh_token: str
    user: UserRead


class RefreshBody(BaseModel):
    # 移动端没有 cookie,把 refresh token 放 body 发来;Web 走 cookie 时不传(留空即可)。
    refresh_token: str | None = None
