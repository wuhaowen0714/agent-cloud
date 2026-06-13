import uuid
from datetime import UTC, datetime, timedelta

import grpc
from agent_cloud.v1 import worker_pb2
from agent_cloud_backend.config import Settings
from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.memory_entry import MemoryConflict, MemoryEntryRepository
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.repositories.user import UserRepository
from agent_cloud_backend.turn.compaction import compact
from agent_cloud_backend.turn.memory_extract import (
    _idle_session_ids,
    apply_remember_calls,
    extract_session_memory,
    scan_idle_and_extract,
)
from agent_cloud_common import Message as CommonMessage
from agent_cloud_common import Role, ToolCall, ToolResult
from sqlalchemy.ext.asyncio import async_sessionmaker


def _settings() -> Settings:
    return Settings(_env_file=None)


def _patch_sessionmaker(monkeypatch, engine):
    import agent_cloud_backend.db as db_module

    monkeypatch.setattr(
        db_module, "_sessionmaker", async_sessionmaker(engine, expire_on_commit=False)
    )


def _patch_worker(
    monkeypatch, *, changed: bool, mem: str, agent_changed: bool = False, agent_mem: str = ""
):
    calls = {"n": 0, "req": None}

    async def _fake(endpoint, req):
        calls["n"] += 1
        calls["req"] = req
        return worker_pb2.ExtractMemoryResponse(
            user_memory=mem,
            agent_memory=agent_mem,
            user_changed=changed,
            agent_changed=agent_changed,
            input_tokens=1,
            output_tokens=1,
        )

    monkeypatch.setattr("agent_cloud_backend.turn.memory_extract.extract_memory_via_worker", _fake)
    return calls


async def _seed(engine, n_rounds: int):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        user = await UserRepository(db).create(User(email=f"{uuid.uuid4()}@e.com"))
        await db.flush()
        agent = await AgentConfigRepository(db).create(
            AgentConfig(user_id=user.id, name="a")
        )
        await db.flush()
        s = await SessionRepository(db).create_for(user.id, agent.id, None, model="m")
        await db.flush()
        mrepo = MessageRepository(db)
        for i in range(n_rounds):
            await mrepo.append(
                s.id, Message(session_id=s.id, seq=0, role="user", content={"text": f"u{i}"})
            )
            await mrepo.append(
                s.id, Message(session_id=s.id, seq=0, role="assistant", content={"text": f"a{i}"})
            )
        await db.commit()
        return s.id, user.id


async def _current(engine, user_id):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        return await MemoryEntryRepository(db).get_current("user", user_id)


async def _current_scope(engine, scope, owner_id):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        return await MemoryEntryRepository(db).get_current(scope, owner_id)


async def _agent_of(engine, sid):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        return (await db.get(Session, sid)).agent_config_id


async def _watermark(engine, sid) -> int:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        return (await db.get(Session, sid)).memory_through_seq


async def test_idle_gate_skips_when_few_rounds(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    calls = _patch_worker(monkeypatch, changed=True, mem="x")
    sid, uid = await _seed(engine, 3)  # < 10
    assert await extract_session_memory(sid, settings=_settings(), reason="idle") is False
    assert calls["n"] == 0  # 没调 worker
    assert await _current(engine, uid) is None


async def test_compaction_ignores_gate_and_writes(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    calls = _patch_worker(monkeypatch, changed=True, mem="- a fact")
    sid, uid = await _seed(engine, 2)
    assert await extract_session_memory(sid, settings=_settings(), reason="compaction") is True
    assert calls["n"] == 1
    cur = await _current(engine, uid)
    assert cur.content == "- a fact"
    assert cur.version == 1
    assert await _watermark(engine, sid) == 3  # 2 rounds → seq 0..3


async def test_idle_extracts_when_enough_rounds(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    _patch_worker(monkeypatch, changed=True, mem="- learned")
    sid, uid = await _seed(engine, 10)
    assert await extract_session_memory(sid, settings=_settings(), reason="idle") is True
    assert (await _current(engine, uid)).content == "- learned"


async def test_unchanged_no_write_but_advances_watermark(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    _patch_worker(monkeypatch, changed=False, mem="ignored")
    sid, uid = await _seed(engine, 10)
    assert await extract_session_memory(sid, settings=_settings(), reason="idle") is False
    assert await _current(engine, uid) is None  # 未写
    assert await _watermark(engine, sid) == 19  # 但水位线推进(10 rounds → max seq 19)


# ---- 双块提炼(spec 2026-06-11-memory-layers):agent 块随 user 块一起对账 ----


async def test_request_carries_current_agent_block(engine, monkeypatch):
    # 请求必须携带 agent 块现值,worker 才能对账/把错层事实搬回正确块
    _patch_sessionmaker(monkeypatch, engine)
    calls = _patch_worker(monkeypatch, changed=False, mem="")
    sid, _uid = await _seed(engine, 2)
    aid = await _agent_of(engine, sid)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        await MemoryEntryRepository(db).write_version(
            "agent", aid, "- 名字:nana", sid, expected_version=0
        )
        await db.commit()
    await extract_session_memory(sid, settings=_settings(), reason="compaction")
    assert calls["req"].agent_memory == "- 名字:nana"


async def test_agent_changed_writes_agent_block(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    _patch_worker(monkeypatch, changed=False, mem="", agent_changed=True, agent_mem="- 名字:nana")
    sid, uid = await _seed(engine, 2)
    aid = await _agent_of(engine, sid)
    assert await extract_session_memory(sid, settings=_settings(), reason="compaction") is True
    cur = await _current_scope(engine, "agent", aid)
    assert cur.content == "- 名字:nana" and cur.version == 1
    assert await _current(engine, uid) is None  # user 块未动
    assert await _watermark(engine, sid) == 3


async def test_both_blocks_changed_writes_both(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    _patch_worker(
        monkeypatch, changed=True, mem="- 中文回复", agent_changed=True, agent_mem="- 名字:nana"
    )
    sid, uid = await _seed(engine, 2)
    aid = await _agent_of(engine, sid)
    assert await extract_session_memory(sid, settings=_settings(), reason="compaction") is True
    assert (await _current(engine, uid)).content == "- 中文回复"
    assert (await _current_scope(engine, "agent", aid)).content == "- 名字:nana"
    assert await _watermark(engine, sid) == 3


async def test_real_concurrent_winner_rolls_back_user_write(engine, monkeypatch):
    # 真实 IntegrityError 路径(非 monkeypatch 模拟):并发赢家在 get_current 与
    # write_version 的窗口抢写 agent v1 → 本次 agent 写撞唯一约束(事务被污染)→
    # user 那笔 flush 与水位线必须一并回滚,赢家数据保留。
    _patch_sessionmaker(monkeypatch, engine)
    sid, uid = await _seed(engine, 2)
    aid = await _agent_of(engine, sid)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _fake(endpoint, req):
        async with maker() as db:  # 独立事务:模拟并发赢家
            await MemoryEntryRepository(db).write_version(
                "agent", aid, "- winner", sid, expected_version=0
            )
            await db.commit()
        return worker_pb2.ExtractMemoryResponse(
            user_memory="- u",
            agent_memory="- loser",
            user_changed=True,
            agent_changed=True,
            input_tokens=1,
            output_tokens=1,
        )

    monkeypatch.setattr("agent_cloud_backend.turn.memory_extract.extract_memory_via_worker", _fake)
    assert await extract_session_memory(sid, settings=_settings(), reason="compaction") is False
    assert await _watermark(engine, sid) == -1  # 未推进
    assert await _current(engine, uid) is None  # user 写一并回滚
    assert (await _current_scope(engine, "agent", aid)).content == "- winner"  # 赢家保留


async def test_any_block_conflict_rolls_back_all_and_keeps_watermark(engine, monkeypatch):
    # agent 块乐观锁冲突 → 整体回滚:user 块本次写入与水位线都不落库(下次重提,与单块语义一致)
    _patch_sessionmaker(monkeypatch, engine)
    _patch_worker(monkeypatch, changed=True, mem="- u", agent_changed=True, agent_mem="- a")
    sid, uid = await _seed(engine, 2)
    orig = MemoryEntryRepository.write_version

    async def fake_write(self, scope, owner_id, content, source_session_id, *, expected_version):
        if scope == "agent":
            raise MemoryConflict("simulated concurrent writer")
        return await orig(
            self, scope, owner_id, content, source_session_id, expected_version=expected_version
        )

    monkeypatch.setattr(MemoryEntryRepository, "write_version", fake_write)
    assert await extract_session_memory(sid, settings=_settings(), reason="compaction") is False
    assert await _watermark(engine, sid) == -1  # 未推进
    assert await _current(engine, uid) is None  # user 块写入一并回滚


async def test_no_new_messages_noop(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    calls = _patch_worker(monkeypatch, changed=True, mem="x")
    sid, _ = await _seed(engine, 10)
    await extract_session_memory(sid, settings=_settings(), reason="compaction")  # 推进到 19
    n = calls["n"]
    # 第二次:没有新消息 → 不调 worker、返回 False
    assert await extract_session_memory(sid, settings=_settings(), reason="compaction") is False
    assert calls["n"] == n


async def _seed_session(engine, *, rounds, idle, running=False, watermark=-1):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        user = await UserRepository(db).create(User(email=f"{uuid.uuid4()}@e.com"))
        await db.flush()
        agent = await AgentConfigRepository(db).create(
            AgentConfig(user_id=user.id, name="a")
        )
        await db.flush()
        s = await SessionRepository(db).create_for(user.id, agent.id, None, model="m")
        await db.flush()
        mrepo = MessageRepository(db)
        for _ in range(rounds):
            await mrepo.append(
                s.id, Message(session_id=s.id, seq=0, role="user", content={"text": "u"})
            )
            await mrepo.append(
                s.id, Message(session_id=s.id, seq=0, role="assistant", content={"text": "a"})
            )
        s.status = "running" if running else "idle"
        s.memory_through_seq = watermark
        if idle:
            s.last_active_at = datetime.now(UTC) - timedelta(hours=1)
        await db.commit()
        return s.id


async def test_idle_session_ids_selection(engine):
    idle_id = await _seed_session(engine, rounds=10, idle=True)
    recent_id = await _seed_session(engine, rounds=10, idle=False)
    nonew_id = await _seed_session(engine, rounds=10, idle=True, watermark=19)  # 已提炼完
    running_id = await _seed_session(engine, rounds=10, idle=True, running=True)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        ids = set(await _idle_session_ids(db, 1800))
    assert idle_id in ids
    assert recent_id not in ids  # 不够空闲
    assert nonew_id not in ids  # 没有新消息
    assert running_id not in ids  # 正在跑


async def test_scan_extracts_idle_sessions(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    calls = _patch_worker(monkeypatch, changed=True, mem="- x")
    await _seed_session(engine, rounds=10, idle=True)
    await _seed_session(engine, rounds=10, idle=False)  # recent → 跳过
    assert await scan_idle_and_extract(_settings()) == 1
    assert calls["n"] == 1


async def test_compact_extracts_memory_before_folding(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)

    async def _fake_summarize(endpoint, req):
        return "summary"

    monkeypatch.setattr("agent_cloud_backend.turn.compaction.summarize_via_worker", _fake_summarize)
    seen = {}

    async def _fake_extract(session_id, *, settings, reason):
        seen["reason"] = reason
        return False

    monkeypatch.setattr("agent_cloud_backend.turn.compaction.extract_session_memory", _fake_extract)
    sid, _ = await _seed(engine, 3)  # 6 条消息,keep_recent=1 → 有可折叠
    await compact(sid, worker_endpoint="x", keep_recent=1, settings=_settings())
    assert seen.get("reason") == "compaction"


async def test_scan_aborts_on_worker_unavailable(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    await _seed_session(engine, rounds=10, idle=True)
    await _seed_session(engine, rounds=10, idle=True)
    attempts = {"n": 0}
    err = grpc.aio.AioRpcError(
        grpc.StatusCode.UNAVAILABLE, grpc.aio.Metadata(), grpc.aio.Metadata()
    )

    async def _boom(session_id, *, settings, reason):
        attempts["n"] += 1
        raise err

    monkeypatch.setattr("agent_cloud_backend.turn.memory_extract.extract_session_memory", _boom)
    assert await scan_idle_and_extract(_settings()) == 0
    assert attempts["n"] == 1  # 第一个 UNAVAILABLE → break,不再连环打 down 的 worker


def _remember_msgs(content, scope=None, *, ok=True):
    """模拟 worker 回传:assistant(remember tool_call)+ tool(对应结果)。ok=worker 是否接受。"""
    args = {"content": content}
    if scope is not None:
        args["scope"] = scope
    return [
        CommonMessage(
            role=Role.ASSISTANT, tool_calls=[ToolCall(id="1", name="remember", arguments=args)]
        ),
        CommonMessage(
            role=Role.TOOL, tool_results=[ToolResult(call_id="1", content="ok", is_error=not ok)]
        ),
    ]


async def test_apply_remember_user_scope(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    sid, uid = await _seed(engine, 1)
    assert await apply_remember_calls(sid, _remember_msgs("likes tea")) == 1
    assert "likes tea" in (await _current(engine, uid)).content


async def test_apply_remember_agent_scope(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    sid, _ = await _seed(engine, 1)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        aid = (await db.get(Session, sid)).agent_config_id
    await apply_remember_calls(sid, _remember_msgs("uses pnpm", scope="agent"))
    async with maker() as db:
        cur = await MemoryEntryRepository(db).get_current("agent", aid)
    assert "uses pnpm" in cur.content


async def test_apply_remember_two_in_one_turn(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    sid, uid = await _seed(engine, 1)
    msgs = [
        CommonMessage(
            role=Role.ASSISTANT,
            tool_calls=[
                ToolCall(id="a", name="remember", arguments={"content": "fact one"}),
                ToolCall(id="b", name="remember", arguments={"content": "fact two"}),
            ],
        ),
        CommonMessage(
            role=Role.TOOL,
            tool_results=[
                ToolResult(call_id="a", content="ok", is_error=False),
                ToolResult(call_id="b", content="ok", is_error=False),
            ],
        ),
    ]
    assert await apply_remember_calls(sid, msgs) == 2
    cur = await _current(engine, uid)
    assert "fact one" in cur.content and "fact two" in cur.content
    assert cur.version == 1  # 同 scope 一回合合并为一个版本


async def test_apply_remember_appends_across_turns(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    sid, uid = await _seed(engine, 1)
    await apply_remember_calls(sid, _remember_msgs("A fact"))
    await apply_remember_calls(sid, _remember_msgs("B fact"))
    cur = await _current(engine, uid)
    assert "A fact" in cur.content and "B fact" in cur.content
    assert cur.version == 2


async def test_apply_remember_skips_rejected_call(engine, monkeypatch):
    # worker 拒绝(is_error 结果)→ backend 不落库(防被禁用时绕过 / 坏参数)
    _patch_sessionmaker(monkeypatch, engine)
    sid, uid = await _seed(engine, 1)
    assert await apply_remember_calls(sid, _remember_msgs("nope", ok=False)) == 0
    assert await _current(engine, uid) is None


async def test_apply_remember_ignores_non_remember(engine, monkeypatch):
    _patch_sessionmaker(monkeypatch, engine)
    sid, uid = await _seed(engine, 1)
    msgs = [
        CommonMessage(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(id="1", name="bash", arguments={"command": "ls"})],
        ),
        CommonMessage(
            role=Role.TOOL, tool_results=[ToolResult(call_id="1", content="ok", is_error=False)]
        ),
    ]
    assert await apply_remember_calls(sid, msgs) == 0
    assert await _current(engine, uid) is None


async def test_apply_remember_respects_backend_enable_gate(engine, monkeypatch):
    # agent.enabled_tools 不含 remember → backend 独立拒绝(纵深防御),即便 result 成功
    _patch_sessionmaker(monkeypatch, engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        user = await UserRepository(db).create(User(email=f"{uuid.uuid4()}@e.com"))
        await db.flush()
        agent = await AgentConfigRepository(db).create(
            AgentConfig(
                user_id=user.id, name="a", enabled_tools=["bash"]
            )
        )
        await db.flush()
        s = await SessionRepository(db).create_for(user.id, agent.id, None, model="m")
        await db.flush()
        sid, uid = s.id, user.id
        await db.commit()
    assert await apply_remember_calls(sid, _remember_msgs("blocked")) == 0
    assert await _current(engine, uid) is None
