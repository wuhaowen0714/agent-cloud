"""手机推送通道(api/push.py)单元测试:连接注册分发 + 半死连接清理 + 鉴权解析。"""

import uuid

from agent_cloud_backend.api.push import _conns, _token_from_subprotocols, push_to_user


class _FakeWs:
    def __init__(self, fail: bool = False):
        self.sent: list[dict] = []
        self._fail = fail

    async def send_json(self, payload):
        if self._fail:
            raise RuntimeError("dead connection")
        self.sent.append(payload)


def test_token_from_subprotocols():
    assert _token_from_subprotocols("bearer, abc.def") == ("bearer", "abc.def")
    assert _token_from_subprotocols("refresh, rtok") == ("refresh", "rtok")
    assert _token_from_subprotocols("bearer,abc") == ("bearer", "abc")
    assert _token_from_subprotocols("") is None
    assert _token_from_subprotocols("abc") is None
    assert _token_from_subprotocols("basic, abc") is None


async def test_push_to_user_delivers_to_all_devices():
    uid = uuid.uuid4()
    a, b = _FakeWs(), _FakeWs()
    _conns[uid] = {a, b}
    try:
        n = await push_to_user(uid, {"type": "notify", "title": "t", "body": "b"})
        assert n == 2
        assert a.sent[0]["title"] == "t" and b.sent[0]["title"] == "t"
    finally:
        _conns.pop(uid, None)


async def test_push_to_user_no_device_is_silent():
    assert await push_to_user(uuid.uuid4(), {"type": "notify"}) == 0


async def test_push_prunes_dead_connections():
    uid = uuid.uuid4()
    ok, dead = _FakeWs(), _FakeWs(fail=True)
    _conns[uid] = {ok, dead}
    try:
        n = await push_to_user(uid, {"type": "notify"})
        assert n == 1
        assert dead not in _conns[uid]  # 半死连接就地清理
        assert ok in _conns[uid]
    finally:
        _conns.pop(uid, None)


# ── 真实鉴权路径(审查 HIGH-1 教训:此前测试手塞 UUID key,绕过了「JWT sub 是 str →
# 注册表 miss」的类型 bug;以下断言必须穿过 _authenticate 才有效)──


async def test_authenticate_bearer_returns_uuid_key(engine, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import agent_cloud_backend.api.push as push_mod
    from agent_cloud_backend.api.push import _authenticate
    from agent_cloud_backend.auth.security import create_access_token
    from agent_cloud_backend.config import Settings
    from agent_cloud_backend.models.user import User
    from agent_cloud_backend.repositories.user import UserRepository

    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(push_mod, "get_sessionmaker", lambda: maker)
    settings = Settings(_env_file=None)
    monkeypatch.setattr(push_mod, "get_settings", lambda: settings)
    async with maker() as db:
        u = await UserRepository(db).create(User(email="push@e.com"))
        await db.commit()
        user_id = u.id

    token = create_access_token(
        str(user_id), secret=settings.auth_secret, ttl_seconds=900
    )
    uid = await _authenticate("bearer", token)
    assert uid == user_id  # UUID 类型:与 push_to_user 的查找 key 严格同型
    assert isinstance(uid, uuid.UUID)


async def test_authenticate_refresh_validates_without_consuming(engine, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy.ext.asyncio import async_sessionmaker

    import agent_cloud_backend.api.push as push_mod
    from agent_cloud_backend.api.push import _authenticate
    from agent_cloud_backend.auth import security
    from agent_cloud_backend.config import Settings
    from agent_cloud_backend.models.refresh_token import RefreshToken
    from agent_cloud_backend.models.user import User
    from agent_cloud_backend.repositories.user import UserRepository

    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(push_mod, "get_sessionmaker", lambda: maker)
    monkeypatch.setattr(push_mod, "get_settings", lambda: Settings(_env_file=None))
    plain, token_hash = security.new_refresh_token()
    async with maker() as db:
        u = await UserRepository(db).create(User(email="push2@e.com"))
        await db.flush()
        db.add(RefreshToken(
            user_id=u.id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + timedelta(days=30),
        ))
        await db.commit()
        user_id = u.id

    # 两次验证都成功 = 不消耗不轮换(与 /auth/refresh 的一次性语义相反,这正是设计点)
    assert await _authenticate("refresh", plain) == user_id
    assert await _authenticate("refresh", plain) == user_id
    # 错 token 拒
    assert await _authenticate("refresh", "wrong-token") is None
