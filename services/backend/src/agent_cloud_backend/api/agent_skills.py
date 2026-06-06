import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.skill import Skill
from agent_cloud_backend.repositories.skill import AgentSkillEnableRepository
from agent_cloud_backend.schemas.skill import AgentSkillsUpdate, SkillRead

router = APIRouter(prefix="/agent-configs", tags=["agent-skills"])


@router.get("/{agent_id}/skills", response_model=list[SkillRead])
async def list_agent_skills(agent_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    return await AgentSkillEnableRepository(session).list_enabled_for_agent(agent_id)


@router.put("/{agent_id}/skills", response_model=list[SkillRead])
async def set_agent_skills(
    agent_id: uuid.UUID,
    body: AgentSkillsUpdate,
    session: AsyncSession = Depends(get_session),
):
    agent = await session.get(AgentConfig, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent config not found")
    if body.skill_ids:
        result = await session.execute(
            select(Skill.id).where(
                Skill.id.in_(body.skill_ids), Skill.user_id == agent.user_id
            )
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
