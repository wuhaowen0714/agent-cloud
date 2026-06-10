import uuid

from sqlalchemy import select

from agent_cloud_backend.models.user_model import UserModel
from agent_cloud_backend.repositories.base import BaseRepository


class UserModelRepository(BaseRepository[UserModel]):
    model = UserModel

    async def list_by_user(self, user_id: uuid.UUID) -> list[UserModel]:
        result = await self.session.execute(
            select(UserModel).where(UserModel.user_id == user_id).order_by(UserModel.created_at)
        )
        return list(result.scalars().all())

    async def get_or_create(self, user_id: uuid.UUID, model_name: str) -> UserModel:
        """幂等:同名已存在则返回已有行(顺序请求足够;并发撞 UNIQUE 由全局 409 兜底)。"""
        existing = (
            await self.session.execute(
                select(UserModel).where(
                    UserModel.user_id == user_id, UserModel.model == model_name
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        return await self.create(UserModel(user_id=user_id, model=model_name))
