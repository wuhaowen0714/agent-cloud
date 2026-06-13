import uuid

from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker


async def _seed(engine, user_id, texts):
    """按 texts 顺序建消息,偶 index=user 奇=assistant;返回 (session_id, [(msg_id, seq), ...])。"""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        agent = await AgentConfigRepository(db).create(
            AgentConfig(user_id=user_id, name="a")
        )
        await db.flush()
        s = await SessionRepository(db).create_for(user_id, agent.id, None, model="m")
        await db.flush()
        out = []
        for i, t in enumerate(texts):
            m = await MessageRepository(db).append(
                s.id,
                Message(
                    session_id=s.id,
                    seq=0,
                    role="user" if i % 2 == 0 else "assistant",
                    content={"text": t, "tool_calls": [], "tool_results": []},
                ),
            )
            out.append((m.id, m.seq))
        await db.commit()
        return s.id, out


async def _read_session(engine, session_id):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        return (
            await db.execute(select(Session).where(Session.id == session_id))
        ).scalar_one()


async def _set_session(engine, session_id, **values):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        await db.execute(update(Session).where(Session.id == session_id).values(**values))
        await db.commit()


async def _delete_message_seq(engine, session_id, seq):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        await db.execute(
            delete(Message).where(Message.session_id == session_id, Message.seq == seq)
        )
        await db.commit()


# ── 回滚 ──────────────────────────────────────────────────────────────


async def test_rollback_deletes_suffix_and_returns_user_text(auth_client, engine):
    sid, msgs = await _seed(engine, uuid.UUID(auth_client.user_id), ["u0", "a0", "u1", "a1", "u2"])
    target_id, _ = msgs[2]  # u1, seq=2
    r = await auth_client.post(f"/sessions/{sid}/rollback", json={"message_id": str(target_id)})
    assert r.status_code == 200, r.text
    assert r.json()["user_text"] == "u1"
    assert r.json()["deleted_count"] == 3  # u1,a1,u2
    listed = (await auth_client.get(f"/sessions/{sid}/messages")).json()
    assert [m["content"]["text"] for m in listed] == ["u0", "a0"]


async def test_rollback_resets_summary_when_target_within_summary(auth_client, engine):
    sid, msgs = await _seed(engine, uuid.UUID(auth_client.user_id), ["u0", "a0", "u1", "a1"])
    # 摘要折叠到 seq=2;记忆提炼到 seq=2
    await _set_session(engine, sid, summary="S", summary_through_seq=2, memory_through_seq=2)
    target_id, _ = msgs[2]  # seq=2 <= summary_through_seq → 丢弃摘要
    r = await auth_client.post(f"/sessions/{sid}/rollback", json={"message_id": str(target_id)})
    assert r.status_code == 200, r.text
    s = await _read_session(engine, sid)
    assert s.summary == "" and s.summary_through_seq == -1
    assert s.memory_through_seq == 1  # min(2, 2-1)
    assert s.last_context_tokens is None


async def test_rollback_keeps_summary_when_target_after_summary(auth_client, engine):
    sid, msgs = await _seed(engine, uuid.UUID(auth_client.user_id), ["u0", "a0", "u1", "a1"])
    await _set_session(engine, sid, summary="S", summary_through_seq=0, memory_through_seq=0)
    target_id, _ = msgs[2]  # seq=2 > summary_through_seq(0) → 保留摘要
    await auth_client.post(f"/sessions/{sid}/rollback", json={"message_id": str(target_id)})
    s = await _read_session(engine, sid)
    assert s.summary == "S" and s.summary_through_seq == 0
    assert s.memory_through_seq == 0  # min(0, 1)


async def test_rollback_409_when_running(auth_client, engine):
    sid, msgs = await _seed(engine, uuid.UUID(auth_client.user_id), ["u0", "a0", "u1"])
    await _set_session(engine, sid, status="running", last_active_at=func.now())
    target_id, _ = msgs[0]
    r = await auth_client.post(f"/sessions/{sid}/rollback", json={"message_id": str(target_id)})
    assert r.status_code == 409


async def test_rollback_422_on_assistant_message(auth_client, engine):
    sid, msgs = await _seed(engine, uuid.UUID(auth_client.user_id), ["u0", "a0"])
    target_id, _ = msgs[1]  # a0 (assistant)
    r = await auth_client.post(f"/sessions/{sid}/rollback", json={"message_id": str(target_id)})
    assert r.status_code == 422


async def test_rollback_404_unowned_session(auth_client):
    r = await auth_client.post(
        f"/sessions/{uuid.uuid4()}/rollback", json={"message_id": str(uuid.uuid4())}
    )
    assert r.status_code == 404


async def test_rollback_releases_lock(auth_client, engine):
    sid, msgs = await _seed(engine, uuid.UUID(auth_client.user_id), ["u0", "a0", "u1", "a1"])
    r1 = await auth_client.post(f"/sessions/{sid}/rollback", json={"message_id": str(msgs[2][0])})
    assert r1.status_code == 200, r1.text
    assert (await _read_session(engine, sid)).status == "idle"  # 锁已释放
    # 二次回滚仍能成功(锁没卡在 running)
    r2 = await auth_client.post(f"/sessions/{sid}/rollback", json={"message_id": str(msgs[0][0])})
    assert r2.status_code == 200, r2.text


async def test_rollback_422_foreign_message(auth_client, engine):
    sid_a, msgs_a = await _seed(engine, uuid.UUID(auth_client.user_id), ["u0", "a0"])
    sid_b, msgs_b = await _seed(engine, uuid.UUID(auth_client.user_id), ["x0", "y0"])
    foreign_id, _ = msgs_b[0]  # 属于 sid_b
    r = await auth_client.post(f"/sessions/{sid_a}/rollback", json={"message_id": str(foreign_id)})
    assert r.status_code == 422


# ── Fork ──────────────────────────────────────────────────────────────


async def test_fork_copies_prefix_to_new_session(auth_client, engine):
    sid, msgs = await _seed(engine, uuid.UUID(auth_client.user_id), ["u0", "a0", "u1", "a1", "u2"])
    target_id, _ = msgs[2]  # u1, seq=2
    r = await auth_client.post(f"/sessions/{sid}/fork", json={"message_id": str(target_id)})
    assert r.status_code == 200, r.text
    new_id = r.json()["new_session_id"]
    assert r.json()["user_text"] == "u1"
    assert new_id != str(sid)
    new_msgs = (await auth_client.get(f"/sessions/{new_id}/messages")).json()
    assert [m["content"]["text"] for m in new_msgs] == ["u0", "a0"]  # seq < 2
    orig_msgs = (await auth_client.get(f"/sessions/{sid}/messages")).json()
    assert [m["content"]["text"] for m in orig_msgs] == ["u0", "a0", "u1", "a1", "u2"]  # 原会话不变


async def test_fork_title_and_summary_carry(auth_client, engine):
    sid, msgs = await _seed(engine, uuid.UUID(auth_client.user_id), ["u0", "a0", "u1", "a1"])
    await _set_session(engine, sid, title="原标题", summary="S", summary_through_seq=1)
    target_id, _ = msgs[2]  # seq=2 > summary_through_seq(1) → 摘要带过去
    r = await auth_client.post(f"/sessions/{sid}/fork", json={"message_id": str(target_id)})
    new = await _read_session(engine, r.json()["new_session_id"])
    assert new.title == "原标题(分支)"
    assert new.summary == "S" and new.summary_through_seq == 1


async def test_fork_drops_summary_when_it_covers_uncopied(auth_client, engine):
    sid, msgs = await _seed(engine, uuid.UUID(auth_client.user_id), ["u0", "a0", "u1", "a1"])
    await _set_session(engine, sid, summary="S", summary_through_seq=3)
    target_id, _ = msgs[2]  # seq=2 <= summary_through_seq(3) → 摘要折叠了没复制的消息 → 丢
    r = await auth_client.post(f"/sessions/{sid}/fork", json={"message_id": str(target_id)})
    new = await _read_session(engine, r.json()["new_session_id"])
    assert new.summary == "" and new.summary_through_seq == -1


async def test_fork_422_on_assistant_message(auth_client, engine):
    sid, msgs = await _seed(engine, uuid.UUID(auth_client.user_id), ["u0", "a0"])
    target_id, _ = msgs[1]  # a0
    r = await auth_client.post(f"/sessions/{sid}/fork", json={"message_id": str(target_id)})
    assert r.status_code == 422


async def test_fork_clamps_cursors_to_copied_prefix(auth_client, engine):
    """评审 I1:新会话游标按【实际复制到的最大 seq】钳,而非按 target。模拟"读 s 后、复制前
    原会话被删得更短"——这里直接删 seq=3 制造比 target-1 更短的前缀;摘要游标(3)领先于实际
    复制到的最大 seq(2)→ 必须丢弃,否则新会话首条新消息会落在陈旧游标下被漏掉。"""
    sid, msgs = await _seed(engine, uuid.UUID(auth_client.user_id), ["u0", "a0", "u1", "a1", "u2"])
    await _set_session(engine, sid, summary="S", summary_through_seq=3, memory_through_seq=3)
    await _delete_message_seq(engine, sid, 3)  # 删 a3 → target=4 之下存活 0,1,2(max=2)
    target_id, _ = msgs[4]  # u2, seq=4(仍存活)
    r = await auth_client.post(f"/sessions/{sid}/fork", json={"message_id": str(target_id)})
    assert r.status_code == 200, r.text
    new = await _read_session(engine, r.json()["new_session_id"])
    assert new.summary == "" and new.summary_through_seq == -1  # 3 > max_copied(2) → 丢弃
    assert new.memory_through_seq == 2  # min(3, 2)
