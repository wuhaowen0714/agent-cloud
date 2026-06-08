import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.auth.security import decode_access_token
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.db import get_session
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.user import UserRepository

__all__ = ["get_session", "get_current_user"]


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> User:
    """从 Authorization: Bearer <access JWT> 解析当前用户;缺失/无效/过期/未知 → 401。"""
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else ""
    uid = decode_access_token(token, secret=settings.auth_secret) if token else None
    if uid is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    try:
        user_uuid = uuid.UUID(uid)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="not authenticated") from exc
    user = await UserRepository(session).get(user_uuid)
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user
