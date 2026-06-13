import base64
import uuid

from agent_cloud_backend import crypto
from agent_cloud_backend.config import Settings
from agent_cloud_backend.models.provider_credential import ProviderCredential
from agent_cloud_backend.models.user import User
from agent_cloud_backend.turn.credentials import resolve_session_key

_KEY_B64 = base64.b64encode(b"\x07" * 32).decode()


async def _mk_user(db):
    u = User(email=f"{uuid.uuid4()}@e.com", password_hash="")
    db.add(u)
    await db.flush()
    return u


async def _mk_cred(db, user_id, plain="sk-real-key", base="https://x/v1"):
    key = crypto.load_credential_key(_KEY_B64)
    row = ProviderCredential(
        user_id=user_id,
        name="c",
        base_url=base,
        api_key_encrypted=crypto.encrypt(plain, key),
        masked=crypto.mask(plain),
        models=[],
    )
    db.add(row)
    await db.flush()
    return row


async def test_resolves_own_credential(session):
    settings = Settings(credential_key=_KEY_B64)
    u = await _mk_user(session)
    cred = await _mk_cred(session, u.id)
    api_key, base_url = await resolve_session_key(session, cred.id, u.id, settings)
    assert api_key == "sk-real-key" and base_url == "https://x/v1"


async def test_none_credential_returns_blank(session):
    settings = Settings(credential_key=_KEY_B64)
    assert await resolve_session_key(session, None, uuid.uuid4(), settings) == ("", "")


async def test_nonexistent_credential_returns_blank(session):
    settings = Settings(credential_key=_KEY_B64)
    assert await resolve_session_key(session, uuid.uuid4(), uuid.uuid4(), settings) == ("", "")


async def test_foreign_credential_falls_back_to_blank(session):
    settings = Settings(credential_key=_KEY_B64)
    owner = await _mk_user(session)
    other = await _mk_user(session)
    cred = await _mk_cred(session, owner.id)
    api_key, base_url = await resolve_session_key(session, cred.id, other.id, settings)
    assert (api_key, base_url) == ("", "")  # 不属本人 → 回退平台
