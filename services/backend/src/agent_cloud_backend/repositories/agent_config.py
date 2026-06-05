import uuid

from sqlalchemy import select

from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.repositories.base import BaseRepository


class AgentConfigRepository(BaseRepository[AgentConfig]):
    model = AgentConfig

    async def list_by_user(self, user_id: uuid.UUID) -> list[AgentConfig]:
        result = await self.session.execute(
            select(AgentConfig).where(AgentConfig.user_id == user_id)
        )
        return list(result.scalars().all())
