import asyncio
import uuid
from types import SimpleNamespace

import grpc
from agent_cloud_common import Message, Role, TextDelta, TurnDone, Usage
from agent_cloud_common.codec import turn_event_to_proto
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

# run_turn 只读 request.agent.model;faked worker stream 忽略 request 其余部分。
_REQ = SimpleNamespace(agent=SimpleNamespace(model="m"))


async def _reassemble():
    # 重试时重新组装请求;测试里 fake worker 忽略请求内容,直接回 _REQ。
    return _REQ


def _patch_global_sessionmaker(monkeypatch, engine):
    import agent_cloud_backend.db as db_module

    monkeypatch.setattr(
        db_module, "_sessionmaker", async_sessionmaker(engine, expire_on_commit=False)
    )


async def _make_session_row(engine):
    from agent_cloud_backend.models.agent_config import AgentConfig
    from agent_cloud_backend.models.user import User
    from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
    from agent_cloud_backend.repositories.session import SessionRepository
    from agent_cloud_backend.repositories.user import UserRepository

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        u = await UserRepository(db).create(User(email=f"{uuid.uuid4()}@e.com"))
        await db.flush()
        a = await AgentConfigRepository(db).create(
            AgentConfig(user_id=u.id, name="a", model="m", provider="p")
        )
        await db.flush()
        s = await SessionRepository(db).create_for(u.id, a.id, None)
        await db.commit()
        return s.id


async def _status(engine, sid):
    from agent_cloud_backend.models.session import Session

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        stmt = (
            select(Session.status)
            .where(Session.id == sid)
            .execution_options(populate_existing=True)
        )
        return (await db.execute(stmt)).scalar_one()


async def _summary(engine, sid):
    from agent_cloud_backend.models.session import Session

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        stmt = (
            select(Session.summary, Session.summary_through_seq)
            .where(Session.id == sid)
            .execution_options(populate_existing=True)
        )
        return (await db.execute(stmt)).one()


async def _seed_messages(engine, sid, n):
    from agent_cloud_backend.models.message import Message as M
    from agent_cloud_backend.repositories.message import MessageRepository

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        for i in range(n):
            await MessageRepository(db).append(
                sid,
                M(
                    session_id=sid,
                    seq=0,
                    role="user" if i % 2 == 0 else "assistant",
                    content={"text": f"m{i}", "tool_calls": [], "tool_results": []},
                ),
            )
        await db.commit()


async def _roles(engine, sid):
    from agent_cloud_backend.models.message import Message as M

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        rows = (
            (await db.execute(select(M.role).where(M.session_id == sid).order_by(M.seq)))
            .scalars()
            .all()
        )
        return list(rows)


def _fake_worker(monkeypatch, gen):
    from agent_cloud_backend.turn import worker_client

    monkeypatch.setattr(worker_client, "stream_turn_via_worker", gen)


async def _acquire(engine, sid):
    from agent_cloud_backend.repositories.session import SessionRepository

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        assert await SessionRepository(db).try_acquire(sid) is True
        await db.commit()


async def test_runner_persists_and_releases_without_any_subscriber(engine, monkeypatch):
    # 核心解耦证明:没有任何订阅者,Runner 也跑完、落库、释放锁、从 Hub 移除
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn.runner import run_turn

    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session_row(engine)
    await _acquire(engine, sid)

    async def _gen(endpoint, request):
        yield turn_event_to_proto(TextDelta(text="hi"))
        yield turn_event_to_proto(
            TurnDone(
                new_messages=[Message(role=Role.ASSISTANT, text="done")],
                usage=Usage(input_tokens=1, output_tokens=2),
                stop_reason="end_turn",
            )
        )

    _fake_worker(monkeypatch, _gen)

    from agent_cloud_backend.config import Settings

    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    await run_turn(
        hub, active, worker_endpoint="x", request=_REQ, reassemble=_reassemble, session_id=sid,
        heartbeat_interval=999, settings=Settings(),
    )

    assert active.done is True
    assert any(e["type"] == "turn_done" for e in active.events)
    assert await _roles(engine, sid) == ["assistant"]  # 助手消息已落库
    assert await _status(engine, sid) == "idle"  # 锁已释放
    assert hub.get(sid) is None  # 已移除


async def test_runner_persists_context_tokens(engine, monkeypatch):
    # /status 用:回合结束把 worker 报告的 context_tokens 落到 session.last_context_tokens。
    from agent_cloud_backend.config import Settings
    from agent_cloud_backend.models.session import Session
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn.runner import run_turn

    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session_row(engine)
    await _acquire(engine, sid)

    async def _gen(endpoint, request):
        yield turn_event_to_proto(
            TurnDone(
                new_messages=[Message(role=Role.ASSISTANT, text="done")],
                usage=Usage(input_tokens=1, output_tokens=2),
                stop_reason="end_turn",
                context_tokens=7,  # 远低于压缩阈值,避免触发主动压缩走真 worker
            )
        )

    _fake_worker(monkeypatch, _gen)

    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    await run_turn(
        hub, active, worker_endpoint="x", request=_REQ, reassemble=_reassemble, session_id=sid,
        heartbeat_interval=999, settings=Settings(),
    )

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        tokens = (
            await db.execute(
                select(Session.last_context_tokens)
                .where(Session.id == sid)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
    assert tokens == 7


async def test_runner_appends_truncation_notice_on_length(engine, monkeypatch):
    # stop_reason="length"(输出被单次 token 上限掐断)→ 落库的 assistant 文本带截断提示;
    # 正常 end_turn 不带(spec 2026-06-10-length-handling §3)。
    from agent_cloud_backend.config import Settings
    from agent_cloud_backend.models.message import Message as M
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn.runner import run_turn

    _patch_global_sessionmaker(monkeypatch, engine)

    async def _run(sid, stop_reason, text):
        async def _gen(endpoint, request):
            yield turn_event_to_proto(
                TurnDone(
                    new_messages=[Message(role=Role.ASSISTANT, text=text)],
                    usage=Usage(input_tokens=1, output_tokens=2),
                    stop_reason=stop_reason,
                    context_tokens=7,
                )
            )

        _fake_worker(monkeypatch, _gen)
        hub = TurnHub()
        active = ActiveTurn(session_id=sid)
        hub.register(active)
        await run_turn(
            hub, active, worker_endpoint="x", request=_REQ, reassemble=_reassemble,
            session_id=sid, heartbeat_interval=999, settings=Settings(),
        )

    async def _last_text(sid):
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            rows = (
                (
                    await db.execute(
                        select(M.content).where(M.session_id == sid).order_by(M.seq)
                    )
                )
                .scalars()
                .all()
            )
        return rows[-1]["text"]

    sid1 = await _make_session_row(engine)
    await _acquire(engine, sid1)
    await _run(sid1, "length", "half an ans")
    text1 = await _last_text(sid1)
    assert text1.startswith("half an ans")
    assert "内容被截断" in text1

    sid2 = await _make_session_row(engine)
    await _acquire(engine, sid2)
    await _run(sid2, "end_turn", "complete answer")
    assert await _last_text(sid2) == "complete answer"  # 不带标记


async def test_runner_cancel_emits_cancelled_and_releases(engine, monkeypatch):
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn.runner import run_turn

    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session_row(engine)
    await _acquire(engine, sid)

    async def _gen(endpoint, request):
        while True:
            yield turn_event_to_proto(TextDelta(text="x"))
            await asyncio.sleep(0.01)

    _fake_worker(monkeypatch, _gen)

    from agent_cloud_backend.config import Settings

    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    active.task = asyncio.create_task(
        run_turn(
            hub,
            active,
            worker_endpoint="x",
            request=_REQ, reassemble=_reassemble,
            session_id=sid,
            heartbeat_interval=999,
            settings=Settings(),
        )
    )
    await asyncio.sleep(0.03)
    active.task.cancel()
    await active.task  # run_turn 吞掉 cancel,干净收尾

    assert active.events[-1] == {"type": "error", "message": "turn cancelled", "recoverable": False}
    assert await _status(engine, sid) == "idle"
    assert hub.get(sid) is None


async def test_drain_hub_releases_stranded_lock_for_never_started_runner(engine, monkeypatch):
    # I3 兜底:runner 在首次运行前就被取消 → 其 finally 从未跑 → 锁残留;drain_hub 兜底释放。
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn.runner import drain_hub

    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session_row(engine)
    await _acquire(engine, sid)

    hub = TurnHub()
    hub.register(ActiveTurn(session_id=sid))  # task 留 None:模拟从未启动/无 runner 的残留
    assert await _status(engine, sid) == "running"

    await drain_hub(hub)

    assert await _status(engine, sid) == "idle"  # 锁被兜底释放
    assert hub.get(sid) is None  # 残留清掉


async def test_runner_post_turn_compaction_when_over_threshold(engine, monkeypatch):
    # 回合后 context_tokens 超阈值 → 主动压缩:session.summary 被填,summary_through_seq 推进。
    from agent_cloud_backend.config import Settings
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn.runner import run_turn

    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session_row(engine)
    await _acquire(engine, sid)
    # 预置 3 条历史(seq 0,1,2);回合再加 1 条 assistant(seq 3)→ 共 4;keep_recent=2 → 折叠 [0,1]
    await _seed_messages(engine, sid, 3)

    async def _gen(endpoint, request):
        yield turn_event_to_proto(
            TurnDone(
                new_messages=[Message(role=Role.ASSISTANT, text="done")],
                usage=Usage(input_tokens=1, output_tokens=2),
                stop_reason="end_turn",
                context_tokens=999,
            )
        )

    _fake_worker(monkeypatch, _gen)

    async def _fake_summarize(endpoint, req):
        return "S"

    monkeypatch.setattr(
        "agent_cloud_backend.turn.compaction.summarize_via_worker", _fake_summarize
    )

    settings = Settings(compaction_token_threshold=10, compaction_keep_recent=2)
    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    await run_turn(
        hub, active, worker_endpoint="x", request=_REQ, reassemble=_reassemble, session_id=sid,
        heartbeat_interval=999, settings=settings,
    )

    assert any(e["type"] == "turn_done" for e in active.events)  # 回合本身成功
    summary, through = await _summary(engine, sid)
    assert summary == "S"
    assert through >= 1  # 折叠边界已推进


async def test_runner_no_compaction_when_under_threshold(engine, monkeypatch):
    # context_tokens 未超阈值 → 不压缩(summarize 不被调用)。
    from agent_cloud_backend.config import Settings
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn.runner import run_turn

    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session_row(engine)
    await _acquire(engine, sid)
    await _seed_messages(engine, sid, 3)

    async def _gen(endpoint, request):
        yield turn_event_to_proto(
            TurnDone(
                new_messages=[Message(role=Role.ASSISTANT, text="done")],
                usage=Usage(input_tokens=1, output_tokens=2),
                stop_reason="end_turn",
                context_tokens=5,
            )
        )

    _fake_worker(monkeypatch, _gen)

    called = {"n": 0}

    async def _fake_summarize(endpoint, req):
        called["n"] += 1
        return "S"

    monkeypatch.setattr(
        "agent_cloud_backend.turn.compaction.summarize_via_worker", _fake_summarize
    )

    settings = Settings(compaction_token_threshold=10, compaction_keep_recent=2)
    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    await run_turn(
        hub, active, worker_endpoint="x", request=_REQ, reassemble=_reassemble, session_id=sid,
        heartbeat_interval=999, settings=settings,
    )

    assert called["n"] == 0  # 5 <= 10,未压缩
    summary, through = await _summary(engine, sid)
    assert summary == "" and through == -1


async def test_runner_per_model_threshold_override_suppresses_compaction(engine, monkeypatch):
    # per-model 覆盖:request 的 model("m")阈值被覆盖成很高 → 即便 ctx 超过全局默认也不压缩。
    # 这验证 model 确实从 request.agent.model 一路传到阈值解析。
    from agent_cloud_backend.config import Settings
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn.runner import run_turn

    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session_row(engine)
    await _acquire(engine, sid)
    await _seed_messages(engine, sid, 3)

    async def _gen(endpoint, request):
        yield turn_event_to_proto(
            TurnDone(
                new_messages=[Message(role=Role.ASSISTANT, text="done")],
                usage=Usage(input_tokens=1, output_tokens=2),
                stop_reason="end_turn",
                context_tokens=500,  # > 全局默认 100,但 < "m" 的 override 10000
            )
        )

    _fake_worker(monkeypatch, _gen)

    called = {"n": 0}

    async def _fake_summarize(endpoint, req):
        called["n"] += 1
        return "S"

    monkeypatch.setattr(
        "agent_cloud_backend.turn.compaction.summarize_via_worker", _fake_summarize
    )

    settings = Settings(
        compaction_token_threshold=100,
        compaction_token_thresholds={"m": 10000},
        compaction_keep_recent=2,
    )
    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    await run_turn(
        hub, active, worker_endpoint="x",
        request=_REQ, reassemble=_reassemble,
        session_id=sid, heartbeat_interval=999, settings=settings,
    )

    assert called["n"] == 0  # "m" override=10000 > ctx 500 → 不压缩
    summary, through = await _summary(engine, sid)
    assert summary == "" and through == -1


async def test_runner_overflow_auto_retries_with_reset(engine, monkeypatch):
    # 首次流抛 RESOURCE_EXHAUSTED → force_compact 有进展 → 发 reset → 重试成功落库(用户无感)。
    from agent_cloud_backend.config import Settings
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn.runner import run_turn

    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session_row(engine)
    await _acquire(engine, sid)
    await _seed_messages(engine, sid, 4)  # 供 force_compact(keep_recent=1)折叠

    calls = {"n": 0}

    async def _gen(endpoint, request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise grpc.aio.AioRpcError(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                initial_metadata=grpc.aio.Metadata(),
                trailing_metadata=grpc.aio.Metadata(),
            )
            yield  # pragma: no cover
        else:
            yield turn_event_to_proto(TextDelta(text="hi"))
            yield turn_event_to_proto(
                TurnDone(
                    new_messages=[Message(role=Role.ASSISTANT, text="done")],
                    usage=Usage(input_tokens=1, output_tokens=2),
                    stop_reason="end_turn",
                )
            )

    _fake_worker(monkeypatch, _gen)

    async def _fake_summarize(endpoint, req):
        return "S"

    monkeypatch.setattr(
        "agent_cloud_backend.turn.compaction.summarize_via_worker", _fake_summarize
    )

    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    await run_turn(
        hub, active, worker_endpoint="x", request=_REQ, reassemble=_reassemble, session_id=sid,
        heartbeat_interval=999, settings=Settings(),
    )

    kinds = [e["type"] for e in active.events]
    assert "reset" in kinds  # 重试前清屏
    assert any(e["type"] == "turn_done" for e in active.events)  # 重试成功
    assert calls["n"] == 2  # 失败 1 次 + 重试 1 次
    # 4 seed + 1 new assistant
    assert await _roles(engine, sid) == ["user", "assistant", "user", "assistant", "assistant"]
    assert await _status(engine, sid) == "idle"


async def test_runner_transient_auto_retries_with_backoff(engine, monkeypatch):
    # 首次抛 UNAVAILABLE → 退避后重试成功(用户无感)。
    from agent_cloud_backend.config import Settings
    from agent_cloud_backend.turn import retry as retry_mod
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn.runner import run_turn

    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session_row(engine)
    await _acquire(engine, sid)
    monkeypatch.setattr(retry_mod.RetryPolicy, "backoff_seconds", lambda self, i: 0.0)

    calls = {"n": 0}

    async def _gen(endpoint, request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise grpc.aio.AioRpcError(
                grpc.StatusCode.UNAVAILABLE,
                initial_metadata=grpc.aio.Metadata(),
                trailing_metadata=grpc.aio.Metadata(),
            )
            yield  # pragma: no cover
        yield turn_event_to_proto(
            TurnDone(
                new_messages=[Message(role=Role.ASSISTANT, text="ok")],
                usage=Usage(input_tokens=1, output_tokens=1),
                stop_reason="end_turn",
            )
        )

    _fake_worker(monkeypatch, _gen)
    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    await run_turn(
        hub, active, worker_endpoint="x", request=_REQ, reassemble=_reassemble, session_id=sid,
        heartbeat_interval=999, settings=Settings(),
    )
    assert calls["n"] == 2
    assert any(e["type"] == "turn_done" for e in active.events)


async def test_runner_transient_exhausted_recoverable_error(engine, monkeypatch):
    # 瞬时错误一直失败 → 退避重试耗尽 → 末事件可恢复(用户可稍后再试)。
    from agent_cloud_backend.config import Settings
    from agent_cloud_backend.turn import retry as retry_mod
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn.runner import run_turn

    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session_row(engine)
    await _acquire(engine, sid)
    monkeypatch.setattr(retry_mod.RetryPolicy, "backoff_seconds", lambda self, i: 0.0)

    async def _gen(endpoint, request):
        raise grpc.aio.AioRpcError(
            grpc.StatusCode.UNAVAILABLE,
            initial_metadata=grpc.aio.Metadata(),
            trailing_metadata=grpc.aio.Metadata(),
        )
        yield  # pragma: no cover

    _fake_worker(monkeypatch, _gen)
    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    await run_turn(
        hub, active, worker_endpoint="x", request=_REQ, reassemble=_reassemble, session_id=sid,
        heartbeat_interval=999, settings=Settings(turn_max_transient_retries=2),
    )
    assert active.events[-1]["type"] == "error"
    assert active.events[-1]["recoverable"] is True  # 瞬时耗尽 → 可恢复
    assert await _status(engine, sid) == "idle"


async def test_runner_resource_exhausted_no_progress_is_non_recoverable(engine, monkeypatch):
    # 仅剩最近一条仍超窗(无可折叠)→ force_compact 无进展 → 末事件不可恢复,别让用户白重试。
    from agent_cloud_backend.config import Settings
    from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub
    from agent_cloud_backend.turn.runner import run_turn

    _patch_global_sessionmaker(monkeypatch, engine)
    sid = await _make_session_row(engine)
    await _acquire(engine, sid)
    await _seed_messages(engine, sid, 1)  # 只有 1 条 → keep_recent=1 无法折叠

    async def _gen(endpoint, request):
        raise grpc.aio.AioRpcError(
            grpc.StatusCode.RESOURCE_EXHAUSTED,
            initial_metadata=grpc.aio.Metadata(),
            trailing_metadata=grpc.aio.Metadata(),
        )
        yield  # pragma: no cover — 使其成为 async generator

    _fake_worker(monkeypatch, _gen)

    called = {"n": 0}

    async def _fake_summarize(endpoint, req):
        called["n"] += 1
        return "X"

    monkeypatch.setattr(
        "agent_cloud_backend.turn.compaction.summarize_via_worker", _fake_summarize
    )

    hub = TurnHub()
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    await run_turn(
        hub, active, worker_endpoint="x", request=_REQ, reassemble=_reassemble, session_id=sid,
        heartbeat_interval=999, settings=Settings(),
    )

    assert active.events[-1]["type"] == "error"
    assert active.events[-1]["recoverable"] is False  # 无进展 → 不可恢复
    assert called["n"] == 0  # 没东西可折叠,未调 summarize
    assert await _status(engine, sid) == "idle"  # 锁仍被释放
