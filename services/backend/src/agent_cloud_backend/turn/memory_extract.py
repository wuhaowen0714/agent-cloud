from __future__ import annotations

import logging
import uuid

import grpc
from agent_cloud.v1 import worker_pb2
from agent_cloud_common.codec import msg_to_proto
from sqlalchemy import func, select

from agent_cloud_backend.config import Settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.memory_entry import MemoryConflict, MemoryEntryRepository
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.turn.credentials import resolve_session_key
from agent_cloud_backend.turn.messages import is_subagent_orm, orm_to_common
from agent_cloud_backend.turn.worker_client import extract_memory_via_worker

logger = logging.getLogger(__name__)

# 每轮空闲扫描最多处理多少会话:限制单次工作量 + 对 worker 的压力。
_SCAN_LIMIT = 100


def _rounds(msgs: list) -> int:
    """对话轮次 = 用户消息条数。"""
    return sum(1 for m in msgs if m.role == "user")


async def extract_session_memory(session_id: uuid.UUID, *, settings: Settings, reason: str) -> bool:
    """从某会话自上次水位线以来的新消息提炼记忆,双块对账:user(跨 agent 共享)与
    agent(本 agent 专属)各自按 changed 写入,错层事实由 worker 提炼时归位
    (spec 2026-06-09 / 2026-06-11-memory-layers)。

    reason='idle' 受 memory_min_rounds 轮次闸约束;reason='compaction' 不设闸(折叠前必提)。
    返回是否写入了新版本。best-effort:并发冲突则放弃本次(下次再提)。
    """
    async with get_sessionmaker()() as db:
        s = await db.get(Session, session_id)
        if s is None:
            return False
        msgs = [
            m
            for m in await MessageRepository(db).list_by_session(s.id)
            if m.seq > s.memory_through_seq and not is_subagent_orm(m)
            # 子 agent 中间过程不喂记忆抽取(只服务前端历史重建)
        ]
        if not msgs:
            return False
        if reason == "idle" and _rounds(msgs) < settings.memory_min_rounds:
            return False  # 轮次闸:只聊一两句就空闲的不值得花一次 LLM

        # BYO-Key:用本人凭据(None/不属本人 → ("","") 回退平台)。key 仅经 worker。
        api_key, base_url = await resolve_session_key(db, s.credential_id, s.user_id, settings)
        mem_repo = MemoryEntryRepository(db)
        cur_user = await mem_repo.get_current("user", s.user_id)
        cur_agent = await mem_repo.get_current("agent", s.agent_config_id)
        req = worker_pb2.ExtractMemoryRequest(
            agent=worker_pb2.Agent(
                model=s.model,
                provider=("sophnet" if s.credential_id is None else "custom"),
                api_key=api_key,
                base_url=base_url,
            ),
            user_memory=cur_user.content if cur_user else "",
            agent_memory=cur_agent.content if cur_agent else "",
            messages=[msg_to_proto(orm_to_common(m)) for m in msgs],
            soft_max_chars=settings.memory_soft_chars,
        )
        resp = await extract_memory_via_worker(settings.worker_endpoint, req)

        max_seq = max(m.seq for m in msgs)
        wrote = False
        # 双块各自乐观锁写入;任一块冲突 → return(事务整体回滚:另一块的写入与
        # 水位线都不落库),下次重提——与原单块语义一致,绝不半写推进。
        for scope, owner_id, changed, content in (
            ("user", s.user_id, resp.user_changed, resp.user_memory),
            ("agent", s.agent_config_id, resp.agent_changed, resp.agent_memory),
        ):
            if not changed:
                continue
            cur = cur_user if scope == "user" else cur_agent
            try:
                await mem_repo.write_version(
                    scope, owner_id, content, s.id, expected_version=cur.version if cur else 0
                )
                await mem_repo.prune(scope, owner_id, settings.memory_max_versions)
                wrote = True
            except MemoryConflict:
                # 并发赢家已写该版本;放弃本次(不推进水位线,下次再提)。
                logger.info("memory write conflict (scope=%s); skipping this pass", scope)
                return False
        s.memory_through_seq = max_seq  # 不论写没写都推进,避免反复重提同一批
        await db.commit()
        return wrote


async def _idle_session_ids(db, idle_seconds: int) -> list[uuid.UUID]:
    """空闲够久(非 running、last_active_at 早于 cutoff)且有未提炼新消息的会话。"""
    cutoff = func.now() - func.make_interval(0, 0, 0, 0, 0, 0, idle_seconds)
    has_new = (
        select(Message.id)
        .where(Message.session_id == Session.id, Message.seq > Session.memory_through_seq)
        .exists()
    )
    rows = await db.execute(
        select(Session.id)
        .where(
            Session.status != "running",
            Session.last_active_at < cutoff,
            has_new,
        )
        .limit(_SCAN_LIMIT)
    )
    return list(rows.scalars().all())


def _accepted_remember_calls(new_messages) -> list:
    """worker【已接受】(tool_result 非错误)、按 call_id 去重的 remember 调用。

    只认 worker 接受的:被禁用/坏参数时 worker 返回 is_error 结果 → 不落库。result 与 call 在
    不同消息里(assistant 带 tool_calls、tool 带 tool_results),故按 call_id 跨消息配对。
    """
    ok_ids = {
        r.call_id
        for m in new_messages
        for r in (getattr(m, "tool_results", None) or [])
        if not r.is_error
    }
    seen: set[str] = set()
    calls = []
    for m in new_messages:
        for c in getattr(m, "tool_calls", None) or []:
            if c.name == "remember" and c.id in ok_ids and c.id not in seen:
                seen.add(c.id)
                calls.append(c)
    return calls


async def _append_facts(scope: str, owner_id, facts: list[str], source_session_id) -> bool:
    """把若干 fact 一次性追加进 (scope, owner) 块;与 auto-reconcile 抢同一块时乐观重试。
    每次尝试用【全新 session】,故冲突(IntegrityError 污染事务)被隔离,不影响消息持久化或他块。"""
    addition = "\n".join(f"- {f}" for f in facts)
    for _ in range(3):
        try:
            async with get_sessionmaker()() as db:
                repo = MemoryEntryRepository(db)
                cur = await repo.get_current(scope, owner_id)
                new_block = f"{cur.content}\n{addition}" if (cur and cur.content) else addition
                await repo.write_version(
                    scope,
                    owner_id,
                    new_block,
                    source_session_id,
                    expected_version=cur.version if cur else 0,
                )
                await db.commit()
            return True
        except MemoryConflict:
            continue  # 新 session 重读当前块再追加
    logger.info("remember: gave up after write conflicts (scope=%s)", scope)
    return False


async def apply_remember_calls(session_id: uuid.UUID, new_messages) -> int:
    """把本回合 agent 主动 remember 的事实追加进记忆块(spec 2026-06-09-remember-tool)。

    **独立事务、best-effort**:与消息持久化解耦(记忆写冲突重试绝不拖垮消息写入)。按 scope 分组,
    每 scope 一次写入(一回合至多 user+agent 两个新版本)。去重/合并/裁剪交给后续 auto-reconcile。
    返回成功追加的事实数。
    """
    calls = _accepted_remember_calls(new_messages)
    if not calls:
        return 0
    async with get_sessionmaker()() as db:
        s = await db.get(Session, session_id)
        if s is None:
            logger.warning("remember: session %s gone; %d call(s) dropped", session_id, len(calls))
            return 0
        agent = await AgentConfigRepository(db).get(s.agent_config_id)
        enabled = list(agent.enabled_tools) if agent else []
        user_id, agent_config_id = s.user_id, s.agent_config_id
    # backend 独立强制 enabled(纵深防御,不仅靠 worker 的 result)。空 = 全部。
    if enabled and "remember" not in enabled:
        return 0
    # session.agent_config_id 必属 session.user(createSession 经 owned_agent 校验),故
    # scope=agent 写的是"本人这个 agent"的块,非跨租户。
    facts_by_scope: dict[str, list[str]] = {}
    for c in calls:
        args = c.arguments or {}
        content = args.get("content")
        scope = args.get("scope", "user")
        if not isinstance(content, str) or not content.strip() or scope not in ("user", "agent"):
            continue
        facts_by_scope.setdefault(scope, []).append(content.strip())
    written = 0
    for scope, facts in facts_by_scope.items():
        owner_id = user_id if scope == "user" else agent_config_id
        if await _append_facts(scope, owner_id, facts, session_id):
            written += len(facts)
    return written


async def scan_idle_and_extract(settings: Settings) -> int:
    """reaper 周期调用:对空闲且攒够新对话的会话各提炼一次(轮次闸在 extract 内生效)。"""
    async with get_sessionmaker()() as db:
        ids = await _idle_session_ids(db, settings.memory_idle_seconds)
    n = 0
    for sid in ids:
        try:
            if await extract_session_memory(sid, settings=settings, reason="idle"):
                n += 1
        except grpc.aio.AioRpcError as e:
            if e.code() == grpc.StatusCode.UNAVAILABLE:
                # worker 不可用:停掉本轮,别对 down 的 worker 连环重连(storm)。
                logger.warning("memory scan: worker unavailable, aborting this pass")
                break
            logger.warning("memory extract RPC failed for session %s: %s", sid, e.code())
        except Exception:
            logger.exception("idle memory extract failed for session %s", sid)
    return n
