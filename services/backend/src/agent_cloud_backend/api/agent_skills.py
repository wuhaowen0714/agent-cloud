import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_current_user, get_session
from agent_cloud_backend.api.ownership import owned_agent
from agent_cloud_backend.models.skill import Skill
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.skill import AgentSkillEnableRepository
from agent_cloud_backend.schemas.skill import AgentSkillsUpdate, SkillRead

router = APIRouter(prefix="/agent-configs", tags=["agent-skills"])


@router.get("/{agent_id}/skills", response_model=list[SkillRead])
async def list_agent_skills(
    agent_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    await owned_agent(agent_id, user.id, session)
    return await AgentSkillEnableRepository(session).list_enabled_for_agent(agent_id)


@router.put("/{agent_id}/skills", response_model=list[SkillRead])
async def set_agent_skills(
    agent_id: uuid.UUID,
    body: AgentSkillsUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    await owned_agent(agent_id, user.id, session)
    if body.skill_ids:
        result = await session.execute(
            select(Skill.id).where(Skill.id.in_(body.skill_ids), Skill.user_id == user.id)
        )
        owned = {r[0] for r in result}
        missing = set(body.skill_ids) - owned
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"skills not owned by user: {sorted(str(m) for m in missing)}",
            )
    repo = AgentSkillEnableRepository(session)
    await repo.replace_enabled_set(agent_id, body.skill_ids)
    await session.commit()
    return await repo.list_enabled_for_agent(agent_id)
