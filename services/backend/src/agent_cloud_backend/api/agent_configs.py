import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_current_user, get_session
from agent_cloud_backend.api.ownership import owned_agent
from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.schemas.agent_config import (
    AgentConfigCreate,
    AgentConfigRead,
    AgentConfigUpdate,
)

router = APIRouter(prefix="/agent-configs", tags=["agent-configs"])


@router.post("", response_model=AgentConfigRead, status_code=status.HTTP_201_CREATED)
async def create_agent_config(
    body: AgentConfigCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
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
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)
    await session.commit()
    await session.refresh(agent)
    return agent
