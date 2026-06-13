import uuid

from sqlalchemy import select

from agent_cloud_backend.models.provider_credential import ProviderCredential
from agent_cloud_backend.repositories.base import BaseRepository


class ProviderCredentialRepository(BaseRepository[ProviderCredential]):
    model = ProviderCredential

    async def create(
        self,
        user_id: uuid.UUID,
        name: str,
        base_url: str,
        api_key_encrypted: bytes,
        masked: str,
        models: list[str],
    ) -> ProviderCredential:
        row = ProviderCredential(
            user_id=user_id,
            name=name,
            base_url=base_url,
            api_key_encrypted=api_key_encrypted,
            masked=masked,
            models=models,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_for_user(self, user_id: uuid.UUID) -> list[ProviderCredential]:
        res = await self.session.execute(
            select(ProviderCredential)
            .where(ProviderCredential.user_id == user_id)
            .order_by(ProviderCredential.created_at)
        )
        return list(res.scalars().all())
