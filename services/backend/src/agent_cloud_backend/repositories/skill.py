import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.models.skill import AgentSkillEnable, Skill
from agent_cloud_backend.repositories.base import BaseRepository


class SkillRepository(BaseRepository[Skill]):
    model = Skill

    async def list_by_user(self, user_id: uuid.UUID) -> list[Skill]:
        result = await self.session.execute(
            select(Skill).where(Skill.user_id == user_id).order_by(Skill.name)
        )
        return list(result.scalars().all())

    async def get_by_user_and_name(self, user_id: uuid.UUID, name: str) -> Skill | None:
        result = await self.session.execute(
            select(Skill).where(Skill.user_id == user_id, Skill.name == name)
        )
        return result.scalar_one_or_none()


class AgentSkillEnableRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def set_enabled(
        self, agent_config_id: uuid.UUID, skill_id: uuid.UUID, enabled: bool
    ) -> AgentSkillEnable:
        row = await self.session.get(AgentSkillEnable, (agent_config_id, skill_id))
        if row is None:
            row = AgentSkillEnable(
                agent_config_id=agent_config_id, skill_id=skill_id, enabled=enabled
            )
            self.session.add(row)
        else:
            row.enabled = enabled
        await self.session.flush()
        return row

    async def replace_enabled_set(
        self, agent_config_id: uuid.UUID, skill_ids: list[uuid.UUID]
    ) -> None:
        result = await self.session.execute(
            select(AgentSkillEnable).where(
                AgentSkillEnable.agent_config_id == agent_config_id
            )
        )
        existing = {r.skill_id: r for r in result.scalars().all()}
        wanted = set(skill_ids)
        for sid in wanted:
            row = existing.get(sid)
            if row is None:
                self.session.add(
                    AgentSkillEnable(
                        agent_config_id=agent_config_id, skill_id=sid, enabled=True
                    )
                )
            else:
                row.enabled = True
        for sid, row in existing.items():
            if sid not in wanted:
                row.enabled = False
        await self.session.flush()

    async def list_enabled_for_agent(self, agent_config_id: uuid.UUID) -> list[Skill]:
        result = await self.session.execute(
            select(Skill)
            .join(AgentSkillEnable, AgentSkillEnable.skill_id == Skill.id)
            .where(
                AgentSkillEnable.agent_config_id == agent_config_id,
                AgentSkillEnable.enabled.is_(True),
            )
            .order_by(Skill.name)
        )
        return list(result.scalars().all())
