import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_current_user, get_session
from agent_cloud_backend.api.ownership import owned_agent, owned_credential
from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.schemas.agent_config import (
    AgentConfigCreate,
    AgentConfigRead,
    AgentConfigUpdate,
)

router = APIRouter(prefix="/agent-configs", tags=["agent-configs"])


async def _validate_key_ref(key_ref: str | None, user_id: uuid.UUID, db: AsyncSession) -> None:
    """key_ref 非空时必须是本人某个 credential 的 id;否则 422(非法)/404(不存在或越权)。
    在写入时拦截,避免悬空/越权的 key_ref 在回合时静默回退全局 Key(用户以为在用自己的 Key)。"""
    if not key_ref:
        return
    try:
        cid = uuid.UUID(key_ref)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid key_ref") from exc
    await owned_credential(cid, user_id, db)  # 不属本人/不存在 → 404


@router.post("", response_model=AgentConfigRead, status_code=status.HTTP_201_CREATED)
async def create_agent_config(
    body: AgentConfigCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    await _validate_key_ref(body.key_ref, user.id, session)
    agent = await AgentConfigRepository(session).create(
        AgentConfig(user_id=user.id, **body.model_dump())
    )
    await session.commit()
    return agent


@router.get("", response_model=list[AgentConfigRead])
async def list_agent_configs(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    return await AgentConfigRepository(session).list_by_user(user.id)


@router.patch("/{agent_id}", response_model=AgentConfigRead)
async def update_agent_config(
    agent_id: uuid.UUID,
    body: AgentConfigUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    agent = await owned_agent(agent_id, user.id, session)
    fields = body.model_dump(exclude_unset=True)
    if "key_ref" in fields:
        await _validate_key_ref(fields["key_ref"], user.id, session)
    for field, value in fields.items():
        setattr(agent, field, value)
    await session.commit()
    await session.refresh(agent)
    return agent
