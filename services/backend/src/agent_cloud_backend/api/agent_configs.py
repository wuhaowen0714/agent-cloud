import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.schemas.agent_config import (
    AgentConfigCreate,
    AgentConfigRead,
    AgentConfigUpdate,
)

router = APIRouter(prefix="/agent-configs", tags=["agent-configs"])


@router.post("", response_model=AgentConfigRead, status_code=status.HTTP_201_CREATED)
async def create_agent_config(
    body: AgentConfigCreate, session: AsyncSession = Depends(get_session)
):
    agent = await AgentConfigRepository(session).create(AgentConfig(**body.model_dump()))
    await session.commit()
    return agent


@router.get("", response_model=list[AgentConfigRead])
async def list_agent_configs(user_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    return await AgentConfigRepository(session).list_by_user(user_id)


@router.patch("/{agent_id}", response_model=AgentConfigRead)
async def update_agent_config(
    agent_id: uuid.UUID, body: AgentConfigUpdate, session: AsyncSession = Depends(get_session)
):
    repo = AgentConfigRepository(session)
    agent = await repo.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent config not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)
    await session.commit()
    await session.refresh(agent)
    return agent
