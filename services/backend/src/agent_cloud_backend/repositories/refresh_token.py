import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from agent_cloud_backend.models.refresh_token import RefreshToken
from agent_cloud_backend.repositories.base import BaseRepository


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    model = RefreshToken

    async def issue(
        self, user_id: uuid.UUID, token_hash: str, expires_at: datetime
    ) -> RefreshToken:
        row = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        """按哈希取行(有效性——是否吊销/过期——由调用方判定)。"""
        res = await self.session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return res.scalar_one_or_none()

    async def revoke(self, token_id: uuid.UUID) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.id == token_id)
            .values(revoked_at=datetime.now(UTC))
        )

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
