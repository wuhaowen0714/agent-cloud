"""租户归属校验:按 id 取资源并确认属于当前用户;不符一律 404(不泄漏存在性)。"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.provider_credential import ProviderCredential
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.models.user_model import UserModel


async def owned_session(session_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession) -> Session:
    s = await db.get(Session, session_id)
    if s is None or s.user_id != user_id:
        raise HTTPException(status_code=404, detail="session not found")
    return s


async def owned_agent(agent_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession) -> AgentConfig:
    a = await db.get(AgentConfig, agent_id)
    if a is None or a.user_id != user_id:
        raise HTTPException(status_code=404, detail="agent config not found")
    return a


async def resolve_owner(
    scope: str, agent_id: uuid.UUID | None, user_id: uuid.UUID, db: AsyncSession
) -> uuid.UUID:
    """context_document / memory 的 owner 推导:scope=user → 当前用户;
    scope=agent → 必须给 agent_id 且该 agent 属本人(否则 404)。其它 scope → 422。"""
    if scope == "user":
        return user_id
    if scope == "agent":
        if agent_id is None:
            raise HTTPException(status_code=422, detail="agent_id required for agent scope")
        await owned_agent(agent_id, user_id, db)
        return agent_id
    raise HTTPException(status_code=422, detail=f"invalid scope: {scope}")


async def owned_credential(
    cred_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
) -> ProviderCredential:
    c = await db.get(ProviderCredential, cred_id)
    if c is None or c.user_id != user_id:
        raise HTTPException(status_code=404, detail="credential not found")
    return c


async def owned_user_model(
    model_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
) -> UserModel:
    m = await db.get(UserModel, model_id)
    if m is None or m.user_id != user_id:
        raise HTTPException(status_code=404, detail="model not found")
    return m
