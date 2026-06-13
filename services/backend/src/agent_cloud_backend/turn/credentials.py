"""回合用凭据解析:按 session.credential_id 取本人凭据 → 解密 → (api_key, base_url)。
None / 不属本人 / 不存在 → ("",""),让 worker 回退平台全局 key(spec §5)。"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend import crypto
from agent_cloud_backend.config import Settings
from agent_cloud_backend.models.provider_credential import ProviderCredential


async def resolve_session_key(
    db: AsyncSession, credential_id: uuid.UUID | None, user_id: uuid.UUID, settings: Settings
) -> tuple[str, str]:
    if credential_id is None:
        return "", ""
    cred = await db.get(ProviderCredential, credential_id)
    if cred is None or cred.user_id != user_id:
        return "", ""  # 不属本人或不存在 → 回退平台,不泄漏、不报错
    key = crypto.load_credential_key(settings.credential_key)
    return crypto.decrypt(cred.api_key_encrypted, key), cred.base_url
