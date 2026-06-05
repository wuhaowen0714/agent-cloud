import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.models.base import Base


class BaseRepository[ModelT: Base]:
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, obj: ModelT) -> ModelT:
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get(self, obj_id: uuid.UUID) -> ModelT | None:
        return await self.session.get(self.model, obj_id)

    async def list(self) -> list[ModelT]:
        result = await self.session.execute(select(self.model))
        return list(result.scalars().all())

    async def delete(self, obj: ModelT) -> None:
        await self.session.delete(obj)
        await self.session.flush()
