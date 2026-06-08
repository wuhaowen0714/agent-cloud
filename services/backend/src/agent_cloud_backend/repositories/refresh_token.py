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

    async def revoke(self, token_id: uuid.UUID) -> bool:
        """原子吊销:仅当该行尚未吊销时置 revoked_at,返回是否本次赢得吊销(rowcount==1)。

        条件 UPDATE + rowcount 判定让并发刷新只有一个赢家(行锁串行化),据此识别"重用"
        (败者读到的是未吊销、却抢不到吊销 → 视为同一 refresh 被并发双花)。参照
        repositories/session.py:try_acquire 的原子加锁范式。
        """
        res = await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.id == token_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        return res.rowcount == 1

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
