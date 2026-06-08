"""回合用凭据解析:按 agent.key_ref 取本人凭据→解密→(api_key, base_url)。
找不到/不属本人/key_ref 非法 → ("",""),让 worker 回退全局 key(spec §5)。"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend import crypto
from agent_cloud_backend.config import Settings
from agent_cloud_backend.models.provider_credential import ProviderCredential


async def resolve_agent_key(
    db: AsyncSession, key_ref: str, user_id: uuid.UUID, settings: Settings
) -> tuple[str, str]:
    if not key_ref:
        return "", ""
    try:
        cid = uuid.UUID(key_ref)
    except ValueError:
        return "", ""
    cred = await db.get(ProviderCredential, cid)
    if cred is None or cred.user_id != user_id:
        return "", ""  # 不属本人或不存在 → 回退全局,不泄漏、不报错
    key = crypto.load_credential_key(settings.credential_key)
    return crypto.decrypt(cred.api_key_encrypted, key), cred.base_url
