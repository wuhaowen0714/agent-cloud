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


# ── 可靠投递(2026-07-07「8 点战报丢推送」复盘):落库为事实源,ack 才算送达,重连补投 ──


async def test_push_to_user_attaches_notification_id():
    uid = uuid.uuid4()
    ws = _FakeWs()
    _conns[uid] = {ws}
    try:
        nid = uuid.uuid4()
        await push_to_user(uid, {"type": "notify", "title": "t"}, notification_id=nid)
        assert ws.sent[0]["id"] == str(nid)
        # 不带 id 的调用保持原形状(payload 不被污染)
        await push_to_user(uid, {"type": "notify", "title": "t2"})
        assert "id" not in ws.sent[1]
    finally:
        _conns.pop(uid, None)


async def _mk_user_with_notifications(maker, n: int, email: str):
    from datetime import UTC, datetime, timedelta

    from agent_cloud_backend.models.notification import Notification
    from agent_cloud_backend.models.user import User
    from agent_cloud_backend.repositories.user import UserRepository

    async with maker() as db:
        u = await UserRepository(db).create(User(email=email))
        await db.flush()
        # created_at 显式错开:同事务 server_default now() 恒定,排序断言不能靠物理顺序
        base = datetime.now(UTC) - timedelta(minutes=n + 1)
        rows = [
            Notification(
                user_id=u.id,
                title=f"t{i}",
                body=f"b{i}",
                created_at=base + timedelta(minutes=i),
            )
            for i in range(n)
        ]
        db.add_all(rows)
        await db.flush()
        ids = [r.id for r in rows]
        await db.commit()
        return u.id, ids


async def test_ack_marks_delivered_with_ownership(engine, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import agent_cloud_backend.api.push as push_mod
    from agent_cloud_backend.api.push import _mark_acked
    from agent_cloud_backend.models.notification import Notification

    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(push_mod, "get_sessionmaker", lambda: maker)
    uid, ids = await _mk_user_with_notifications(maker, 1, "ack@e.com")
    other, _ = await _mk_user_with_notifications(maker, 0, "ack-other@e.com")

    await _mark_acked(other, str(ids[0]))  # 别人 ack 我的通知:归属校验拦下
    async with maker() as db:
        assert (await db.get(Notification, ids[0])).delivered_at is None

    await _mark_acked(uid, str(ids[0]))  # 本人 ack 生效
    async with maker() as db:
        assert (await db.get(Notification, ids[0])).delivered_at is not None

    await _mark_acked(uid, "not-a-uuid")  # 坏 id 静默忽略
    await _mark_acked(uid, None)


async def test_backlog_resend_on_connect(engine, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import agent_cloud_backend.api.push as push_mod
    from agent_cloud_backend.api.push import _send_backlog

    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(push_mod, "get_sessionmaker", lambda: maker)
    uid, ids = await _mk_user_with_notifications(maker, 3, "backlog@e.com")

    ws = _FakeWs()
    await _send_backlog(ws, uid)
    assert [m["title"] for m in ws.sent] == ["t0", "t1", "t2"]  # 升序=按时间先后弹
    assert {m["id"] for m in ws.sent} == {str(i) for i in ids}
    assert all(m["type"] == "notify" for m in ws.sent)
    # 未 ack:依然未送达,下次重连再补(at-least-once)
    ws2 = _FakeWs()
    await _send_backlog(ws2, uid)
    assert len(ws2.sent) == 3


async def test_backlog_caps_and_drops_stale(engine, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import agent_cloud_backend.api.push as push_mod
    from agent_cloud_backend.api.push import BACKLOG_LIMIT, _send_backlog
    from agent_cloud_backend.repositories.notification import NotificationRepository

    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(push_mod, "get_sessionmaker", lambda: maker)
    uid, _ = await _mk_user_with_notifications(maker, BACKLOG_LIMIT + 5, "flood@e.com")

    ws = _FakeWs()
    await _send_backlog(ws, uid)
    # 只补最新 LIMIT 条(60s 间隔任务断链一夜攒百条的轰炸防线)
    assert len(ws.sent) == BACKLOG_LIMIT
    assert ws.sent[0]["title"] == "t5" and ws.sent[-1]["title"] == f"t{BACKLOG_LIMIT + 4}"
    # 更旧 5 条被放弃(标 delivered),不会在下次重连再冒出来
    async with maker() as db:
        remaining = await NotificationRepository(db).list_undelivered(uid)
        assert len(remaining) == BACKLOG_LIMIT


async def test_backlog_drops_expired(engine, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy.ext.asyncio import async_sessionmaker

    import agent_cloud_backend.api.push as push_mod
    from agent_cloud_backend.api.push import _send_backlog
    from agent_cloud_backend.models.notification import Notification
    from agent_cloud_backend.models.user import User
    from agent_cloud_backend.repositories.notification import NotificationRepository
    from agent_cloud_backend.repositories.user import UserRepository

    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(push_mod, "get_sessionmaker", lambda: maker)
    async with maker() as db:
        u = await UserRepository(db).create(User(email="stale@e.com"))
        await db.flush()
        now = datetime.now(UTC)
        db.add_all([
            # 3 天前:修复上线前攒的历史积压,不该当新通知弹出来
            Notification(user_id=u.id, title="old", body="b",
                         created_at=now - timedelta(days=3)),
            Notification(user_id=u.id, title="new", body="b",
                         created_at=now - timedelta(minutes=5)),
        ])
        await db.commit()
        uid = u.id

    ws = _FakeWs()
    await _send_backlog(ws, uid)
    assert [m["title"] for m in ws.sent] == ["new"]  # 只补 48h 内的
    async with maker() as db:
        # 过期的被放弃(标 delivered)不再出现;新的未 ack 保持未送达(at-least-once)
        remaining = await NotificationRepository(db).list_undelivered(uid)
        assert [n.title for n in remaining] == ["new"]
