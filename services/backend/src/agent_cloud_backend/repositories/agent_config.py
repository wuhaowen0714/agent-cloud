import uuid

from sqlalchemy import select

from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.repositories.base import BaseRepository


class AgentConfigRepository(BaseRepository[AgentConfig]):
    model = AgentConfig

    async def list_by_user(self, user_id: uuid.UUID) -> list[AgentConfig]:
        # 稳定排序:无 ORDER BY 时行序随 UPDATE(改名等)漂移,前端「选第一个」会乱跳
        result = await self.session.execute(
            select(AgentConfig)
            .where(AgentConfig.user_id == user_id)
            .order_by(AgentConfig.created_at, AgentConfig.id)
        )
        return list(result.scalars().all())
