# 智能体记忆(自整合单块)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 superpowers:subagent-driven-development 或 superpowers:executing-plans 逐任务实现。步骤用 `- [ ]` 复选框跟踪。
> **本仓库注意**:子 agent 大批量写入会截断 → 机械实现由 controller 直接做,子 agent 仅用于审查(diff 内联)。每个任务跑完整回归再提交。后端测试:`cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker"`。

**Goal:** 把"只追加、最近 50 条全量注入"的记忆,升级成「每作用域一块、LLM 读旧块后重写(更新/淘汰)、2000 字软上限」的自整合记忆。v1 只自动提炼 **user 层**;触发 = 空闲(≥10 轮闸)+ 压缩前。

**Architecture:** 提炼是 LLM 调用 → 走 worker(key 留 worker):backend 编排(取 delta + 当前块 + 解 key)→ 新增 gRPC `ExtractMemory` → worker reconcile → backend 写版本快照(乐观并发)+ 推进水位线。注入从"最近 N"换成"当前块(latest version)"。

**Tech Stack:** Python 3.12 / uv / FastAPI / SQLAlchemy(async)+ Alembic / gRPC / openai SDK;React + Vitest。设计见 `docs/superpowers/specs/2026-06-09-agent-memory-design.md`。

---

## 文件结构

| 文件 | 动作 | 责任 |
|---|---|---|
| `protos/agent_cloud/v1/worker.proto` | 改 | 加 `ExtractMemory` RPC + 两个 message |
| `packages/common/src/agent_cloud/v1/worker_pb2*.py` | 生成 | `bash scripts/gen_protos.sh` |
| `services/backend/.../config.py` | 改 | memory 配置项 |
| `services/backend/.../models/memory_entry.py` | 改 | 加 `version` |
| `services/backend/.../models/session.py` | 改 | 加 `memory_through_seq` |
| `services/backend/alembic/versions/<new>.py` | 建 | 迁移:列 + 唯一约束 + 回填 |
| `services/backend/.../repositories/memory_entry.py` | 改 | `get_current` / `write_version`(乐观并发)/ `prune` |
| `services/worker/.../memory_extract.py` | 建 | reconcile 提示词 + 解析(user 层) |
| `services/worker/.../server.py` | 改 | `ExtractMemory` handler(镜像 `Summarize`) |
| `services/backend/.../turn/worker_client.py` | 改 | `extract_memory_via_worker` |
| `services/backend/.../turn/memory_extract.py` | 建 | 编排:delta+轮次闸+解 key+调 worker+写版本+推水位 |
| `services/backend/.../turn/compaction.py` | 改 | 折叠前触发提炼 |
| `services/backend/.../main.py` | 改 | reaper loop 加空闲提炼扫描 |
| `services/backend/.../turn/assemble.py` | 改 | 注入改取当前块(latest) |
| `services/backend/.../api/memory_entries.py` + `schemas/memory_entry.py` | 改 | GET/PUT/DELETE 当前块 |
| `frontend/src/api/client.ts` + `components/settings/MemoryPanel.tsx` 等 | 建/改 | 记忆查看/编辑/清空 UI |

---

## Task 1:proto — `ExtractMemory` RPC

**Files:** Modify `protos/agent_cloud/v1/worker.proto`;Generate `packages/common/src/agent_cloud/v1/worker_pb2*.py`;Test `packages/common/tests/test_proto_smoke.py`(若无则建)

- [ ] **Step 1 失败测试**
```python
# packages/common/tests/test_proto_smoke.py
from agent_cloud.v1 import worker_pb2
def test_extract_memory_messages_exist():
    req = worker_pb2.ExtractMemoryRequest(user_memory="x", soft_max_chars=2000)
    assert req.user_memory == "x" and req.soft_max_chars == 2000
    resp = worker_pb2.ExtractMemoryResponse(user_memory="y", user_changed=True)
    assert resp.user_changed is True
```
- [ ] **Step 2 跑(应失败)**:`cd packages/common && uv run pytest tests/test_proto_smoke.py -q` → `AttributeError: ExtractMemoryRequest`
- [ ] **Step 3 改 proto**(在 `service Worker` 内加 rpc,文件末加 message):
```proto
  rpc ExtractMemory(ExtractMemoryRequest) returns (ExtractMemoryResponse);
```
```proto
message ExtractMemoryRequest {
  Agent agent = 1;            // 复用 model/provider/api_key/base_url
  string user_memory = 2;     // 当前 user 块(可空)
  string agent_memory = 3;    // 当前 agent 块(v1 仅透传,不改)
  repeated Msg messages = 4;  // 自上次水位线以来的新消息
  int32 soft_max_chars = 5;   // 软上限(只引导,不硬截断)
}
message ExtractMemoryResponse {
  string user_memory = 1;
  string agent_memory = 2;
  bool user_changed = 3;
  bool agent_changed = 4;
  int64 input_tokens = 5;
  int64 output_tokens = 6;
}
```
- [ ] **Step 4 生成**:`bash scripts/gen_protos.sh`
- [ ] **Step 5 跑(应通过)**:同 Step 2 → PASS
- [ ] **Step 6 提交**:`git add protos packages/common && git commit -m "feat(proto): ExtractMemory RPC for memory extraction"`

---

## Task 2:backend 配置项

**Files:** Modify `services/backend/src/agent_cloud_backend/config.py`;Test `services/backend/tests/test_config.py`(追加)

- [ ] **Step 1 失败测试**
```python
def test_memory_settings_defaults():
    from agent_cloud_backend.config import Settings
    s = Settings()
    assert s.memory_soft_chars == 2000
    assert s.memory_min_rounds == 10
    assert s.memory_max_versions == 20
```
- [ ] **Step 2 跑** → 失败(AttributeError)
- [ ] **Step 3 实现**(在 `Settings` 加,放 BYO-Key 段后):
```python
    # 智能体记忆(spec 2026-06-09):自整合单块。
    memory_soft_chars: int = 2000        # 每块软上限,仅引导 LLM,不硬截断
    memory_min_rounds: int = 10          # 空闲提炼:自上次提炼以来新对话轮次 ≥ 此值才提
    memory_idle_seconds: int = 1800      # 空闲多久算"可提炼"(默认同沙箱 idle TTL)
    memory_max_versions: int = 20        # 每块保留的版本数,超出裁剪
```
- [ ] **Step 4 跑** → PASS
- [ ] **Step 5 提交**:`git commit -am "feat(backend): memory config (soft_chars/min_rounds/idle/max_versions)"`

---

## Task 3:数据模型 + 迁移

**Files:** Modify `models/memory_entry.py`、`models/session.py`;Create `alembic/versions/<rev>_memory_versioning.py`;Test `tests/test_migration.py`(沿用现有模式)+ `tests/test_memory_repo.py`

- [ ] **Step 1 改模型**
`models/memory_entry.py` 加:
```python
    version: Mapped[int] = mapped_column(nullable=False, default=1)
```
并加表级唯一约束(类体内):
```python
    from sqlalchemy import UniqueConstraint
    __table_args__ = (UniqueConstraint("scope", "owner_id", "version", name="uq_memory_scope_owner_version"),)
```
`models/session.py` 加(紧挨 `summary_through_seq`):
```python
    memory_through_seq: Mapped[int] = mapped_column(default=-1, nullable=False)
```
- [ ] **Step 2 生成迁移**:`cd services/backend && uv run alembic revision -m "memory versioning"`;在生成文件里写 `upgrade()`:
```python
def upgrade():
    op.add_column("memory_entries", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("sessions", sa.Column("memory_through_seq", sa.Integer(), nullable=False, server_default="-1"))
    # 回填:同 (scope,owner_id) 的旧"逐条"行各给递增 version,避免唯一约束冲突;
    # 最新一条即成为"当前块",下次提炼会整体重写。
    op.execute("""
        UPDATE memory_entries m SET version = sub.rn FROM (
          SELECT id, ROW_NUMBER() OVER (PARTITION BY scope, owner_id ORDER BY created_at, id) rn
          FROM memory_entries
        ) sub WHERE m.id = sub.id
    """)
    op.create_unique_constraint("uq_memory_scope_owner_version", "memory_entries", ["scope", "owner_id", "version"])
    op.alter_column("memory_entries", "version", server_default=None)
    op.alter_column("sessions", "memory_through_seq", server_default=None)

def downgrade():
    op.drop_constraint("uq_memory_scope_owner_version", "memory_entries", type_="unique")
    op.drop_column("sessions", "memory_through_seq")
    op.drop_column("memory_entries", "version")
```
- [ ] **Step 3 测试**:`test_migration.py` 已有"升到 head 不报错"的模式 → 确认通过;`cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_migration.py -q`
- [ ] **Step 4 提交**:`git commit -am "feat(backend): memory_entries.version + sessions.memory_through_seq (migration)"`

---

## Task 4:repository — 当前块读 + 版本写(乐观并发)+ 裁剪

**Files:** Modify `repositories/memory_entry.py`;Test `tests/test_memory_repo.py`

- [ ] **Step 1 失败测试**
```python
import pytest, uuid
from agent_cloud_backend.repositories.memory_entry import MemoryEntryRepository, MemoryConflict

async def test_write_and_get_current(session):
    repo = MemoryEntryRepository(session)
    oid = uuid.uuid4()
    e1 = await repo.write_version("user", oid, "v1", None, expected_version=0); await session.commit()
    cur = await repo.get_current("user", oid)
    assert cur.content == "v1" and cur.version == 1
    await repo.write_version("user", oid, "v2", None, expected_version=1); await session.commit()
    assert (await repo.get_current("user", oid)).content == "v2"

async def test_optimistic_conflict(session):
    repo = MemoryEntryRepository(session)
    oid = uuid.uuid4()
    await repo.write_version("user", oid, "v1", None, expected_version=0); await session.commit()
    with pytest.raises(MemoryConflict):       # 第二个写 version=1 的并发者
        await repo.write_version("user", oid, "x", None, expected_version=0); await session.commit()
```
- [ ] **Step 2 跑** → 失败
- [ ] **Step 3 实现**(加到 repo;`get_current`=max version;`write_version` 插 expected+1,唯一约束冲突→`MemoryConflict`):
```python
from sqlalchemy.exc import IntegrityError

class MemoryConflict(Exception):
    """并发写同一 (scope,owner) 版本冲突;调用方应重读当前块后重试。"""

# class MemoryEntryRepository(...):
    async def get_current(self, scope: str, owner_id: uuid.UUID) -> MemoryEntry | None:
        r = await self.session.execute(
            select(MemoryEntry).where(MemoryEntry.scope == scope, MemoryEntry.owner_id == owner_id)
            .order_by(MemoryEntry.version.desc()).limit(1)
        )
        return r.scalars().first()

    async def write_version(self, scope, owner_id, content, source_session_id, *, expected_version) -> MemoryEntry:
        entry = MemoryEntry(scope=scope, owner_id=owner_id, content=content,
                            source_session_id=source_session_id, version=expected_version + 1)
        self.session.add(entry)
        try:
            await self.session.flush()
        except IntegrityError as e:
            raise MemoryConflict(str(e)) from e
        return entry

    async def prune(self, scope, owner_id, keep: int) -> int:
        rows = (await self.session.execute(
            select(MemoryEntry.id).where(MemoryEntry.scope == scope, MemoryEntry.owner_id == owner_id)
            .order_by(MemoryEntry.version.desc()).offset(keep)
        )).scalars().all()
        for rid in rows:
            await self.session.delete(await self.session.get(MemoryEntry, rid))
        return len(rows)
```
（保留旧 `append`/`list_for_context` 暂不删,Task 8 换掉 assemble 的调用后,Task 9 一并清理。）
- [ ] **Step 4 跑** → PASS
- [ ] **Step 5 提交**:`git commit -am "feat(backend): memory repo get_current/write_version(optimistic)/prune"`

---

## Task 5:worker — `ExtractMemory` reconcile(user 层)

**Files:** Create `services/worker/src/agent_cloud_worker/memory_extract.py`;Modify `server.py`;Test `services/worker/tests/test_memory_extract.py`

- [ ] **Step 1 失败测试**(mock provider 返回 JSON;验证新增/无变化/解析失败回退):
```python
import pytest
from agent_cloud_worker.memory_extract import reconcile_user_memory

class FakeProvider:
    def __init__(self, text): self._t = text
    async def complete(self, *, system, messages, max_tokens=None):
        from agent_cloud_common import Completion, Usage  # 按实际 provider 返回类型
        return Completion(text=self._t, usage=Usage(input_tokens=1, output_tokens=1))

async def test_reconcile_adds():
    p = FakeProvider('{"changed": true, "memory": "- prefers Python"}')
    out, changed, _ = await reconcile_user_memory(p, current="", messages=[], soft_max_chars=2000)
    assert changed and "Python" in out

async def test_reconcile_noop_on_unparseable():
    p = FakeProvider("not json")
    out, changed, _ = await reconcile_user_memory(p, current="- existing", messages=[], soft_max_chars=2000)
    assert out == "- existing" and changed is False
```
> 注:`Provider.complete` 的真实签名/返回类型以 `services/worker/.../provider.py` 为准(Summarize 已用之),测试与实现按其调整。
- [ ] **Step 2 跑** → 失败
- [ ] **Step 3 实现** `memory_extract.py`:
```python
from __future__ import annotations
import json

_SYSTEM = """You maintain a compact MEMORY about a USER, reused across all their agents.
Given the CURRENT memory and the RECENT conversation, return the UPDATED memory.
Rules:
- Keep ONLY durable, cross-agent facts about the person: identity, role, timezone,
  language, stable preferences (reply language, verbosity, coding style, tooling), long-term goals.
- DO NOT store: one-off/in-session details, low-confidence guesses, or things specific to one
  agent's task (those belong elsewhere).
- PRESERVE existing facts verbatim unless the conversation updates or contradicts them
  (newer wins). Remove outdated/contradicted facts. Deduplicate.
- Keep it concise, ideally under {soft} characters (soft target; be terse, merge related facts).
- Output STRICT JSON: {{"changed": <bool>, "memory": "<the full updated memory as markdown bullets>"}}.
  Set changed=false and echo the current memory if there is nothing durable to add/change."""

def _parse(text: str, current: str) -> tuple[str, bool]:
    s = text.strip()
    if s.startswith("```"):                       # 去掉可能的 code fence
        s = s.split("```", 2)[1].lstrip("json").strip() if s.count("```") >= 2 else s
    try:
        obj = json.loads(s)
        mem = str(obj["memory"]); changed = bool(obj["changed"])
        return (mem, changed) if changed else (current, False)
    except Exception:
        return current, False                     # 解析失败 = 不动现有块

async def reconcile_user_memory(provider, *, current: str, messages: list, soft_max_chars: int):
    convo = "\n".join(f"{m.role}: {m.content.text}" for m in messages) or "(no new messages)"
    user_prompt = f"CURRENT MEMORY:\n{current or '(empty)'}\n\nRECENT CONVERSATION:\n{convo}"
    comp = await provider.complete(
        system=_SYSTEM.format(soft=soft_max_chars),
        messages=[_user_msg(user_prompt)],        # 按 provider 的 Message 构造
    )
    mem, changed = _parse(comp.text, current)
    return mem, changed, comp.usage
```
- [ ] **Step 4 改 server.py** 加 handler(镜像 `Summarize`):
```python
    async def ExtractMemory(self, request, context):
        try:
            provider = self._provider_factory(request.agent.model, request.agent.provider,
                                              request.agent.api_key, request.agent.base_url)
        except Exception as exc:
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, f"provider unavailable: {exc}")
        from agent_cloud_worker.memory_extract import reconcile_user_memory
        msgs = [_msg_from_proto(m) for m in request.messages]   # 复用 server.py 已有的转换
        mem, changed, usage = await reconcile_user_memory(
            provider, current=request.user_memory, messages=msgs, soft_max_chars=request.soft_max_chars or 2000)
        return worker_pb2.ExtractMemoryResponse(
            user_memory=mem, user_changed=changed,
            agent_memory=request.agent_memory, agent_changed=False,
            input_tokens=usage.input_tokens, output_tokens=usage.output_tokens)
```
- [ ] **Step 5 跑**:`cd services/worker && uv run pytest tests/test_memory_extract.py -q` → PASS
- [ ] **Step 6 提交**:`git commit -am "feat(worker): ExtractMemory — reconcile user memory (user-layer v1)"`

---

## Task 6:backend 编排 — worker_client + memory_extract

**Files:** Modify `turn/worker_client.py`;Create `turn/memory_extract.py`;Test `tests/test_memory_extract_orch.py`

- [ ] **Step 1 client 方法**(镜像 `summarize_via_worker`):
```python
async def extract_memory_via_worker(worker_endpoint, request):  # request: ExtractMemoryRequest
    async with _channel(worker_endpoint) as channel:            # 用现有 channel helper
        return await worker_pb2_grpc.WorkerStub(channel).ExtractMemory(request)
```
- [ ] **Step 2 失败测试**(monkeypatch worker_client + worker;验证轮次闸/水位/写版本/无变化跳过):
```python
async def test_idle_gate_skips_when_few_rounds(session, monkeypatch, make_session_with_messages):
    s = await make_session_with_messages(rounds=3)               # < 10
    called = monkeypatch_extract_returns(monkeypatch, changed=True, mem="x")
    wrote = await extract_session_memory(s.id, settings=Settings(), reason="idle")
    assert wrote is False and called["n"] == 0                   # 没调 worker

async def test_compaction_reason_ignores_gate_and_writes(session, monkeypatch, make_session_with_messages):
    s = await make_session_with_messages(rounds=2)
    monkeypatch_extract_returns(monkeypatch, changed=True, mem="- fact")
    assert await extract_session_memory(s.id, settings=Settings(), reason="compaction") is True
    cur = await MemoryEntryRepository(session).get_current("user", s.user_id)
    assert cur.content == "- fact"
    s2 = await session.get(Session, s.id); assert s2.memory_through_seq == max_seq_of(s)

async def test_unchanged_no_write(...):  # changed=False → 不写、但仍推进水位线
```
- [ ] **Step 3 跑** → 失败
- [ ] **Step 4 实现** `turn/memory_extract.py`:
```python
from __future__ import annotations
import uuid
from agent_cloud.v1 import worker_pb2
from agent_cloud_common.codec import msg_to_proto
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.db import session_scope            # 按现有获取 DB session 的方式
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.memory_entry import MemoryEntryRepository, MemoryConflict
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.turn.credentials import resolve_agent_key
from agent_cloud_backend.turn.messages import orm_to_common
from agent_cloud_backend.turn.worker_client import extract_memory_via_worker

def _rounds(msgs) -> int:
    return sum(1 for m in msgs if m.role == "user")

async def extract_session_memory(session_id: uuid.UUID, *, settings: Settings, reason: str) -> bool:
    """reason: 'idle' | 'compaction'。返回是否写入了新版本。"""
    async with session_scope() as db:
        s = await db.get(Session, session_id)
        if s is None:
            return False
        msgs = [m for m in await MessageRepository(db).list_by_session(s.id) if m.seq > s.memory_through_seq]
        if not msgs:
            return False
        if reason == "idle" and _rounds(msgs) < settings.memory_min_rounds:
            return False                                   # 轮次闸:只对空闲生效
        agent = await AgentConfigRepository(db).get(s.agent_config_id)
        api_key, base_url = await resolve_agent_key(db, agent.key_ref or "", s.user_id, settings)
        mem_repo = MemoryEntryRepository(db)
        cur = await mem_repo.get_current("user", s.user_id)
        req = worker_pb2.ExtractMemoryRequest(
            agent=worker_pb2.Agent(model=agent.model, provider=agent.provider,
                                   api_key=api_key, base_url=base_url),
            user_memory=cur.content if cur else "",
            messages=[msg_to_proto(orm_to_common(m)) for m in msgs],
            soft_max_chars=settings.memory_soft_chars)
        resp = await extract_memory_via_worker(settings.worker_endpoint, req)
        wrote = False
        max_seq = max(m.seq for m in msgs)
        if resp.user_changed:
            expected = cur.version if cur else 0
            try:
                await mem_repo.write_version("user", s.user_id, resp.user_memory, s.id, expected_version=expected)
                await mem_repo.prune("user", s.user_id, settings.memory_max_versions)
                wrote = True
            except MemoryConflict:
                return False                               # 并发写赢家已落库;本次放弃(下次空闲再提)
        s.memory_through_seq = max_seq                       # 不论写没写都推进,避免反复重提同一批
        await db.commit()
        return wrote
```
> `session_scope` / `_channel` 以现有代码为准(compaction.py / worker_client.py 已有同类用法,照搬)。
- [ ] **Step 5 跑** → PASS
- [ ] **Step 6 提交**:`git commit -am "feat(backend): memory extraction orchestration (round-gate, watermark, optimistic write)"`

---

## Task 7:触发 — 空闲扫描 + 压缩前

**Files:** Modify `main.py`(reaper loop)、`turn/compaction.py`;Test `tests/test_memory_triggers.py`

- [ ] **Step 1 空闲扫描函数**(加到 `turn/memory_extract.py`):
```python
async def scan_idle_and_extract(settings: Settings) -> int:
    """reaper 周期调用:对空闲够久 + 有 ≥min_rounds 新消息的会话各提炼一次。"""
    async with session_scope() as db:
        ids = await _idle_session_ids(db, settings.memory_idle_seconds)   # status='idle' 且 last_active_at < now-idle
    n = 0
    for sid in ids:
        if await extract_session_memory(sid, settings=settings, reason="idle"):
            n += 1
    return n
```
- [ ] **Step 2 接 reaper**(`main.py` `_reaper_loop` 里,`reap_idle()` 之后加):
```python
        try:
            from agent_cloud_backend.turn.memory_extract import scan_idle_and_extract
            await scan_idle_and_extract(settings)
        except Exception:
            logger.exception("memory idle-extract pass failed")
```
- [ ] **Step 3 接压缩**(`turn/compaction.py` `compact()` 内,**在推进 `summary_through_seq`/写 summary 之前**):
```python
        # 折叠前先提炼记忆,否则细节被摘要抹掉(不受轮次闸限制)。
        from agent_cloud_backend.turn.memory_extract import extract_session_memory
        await extract_session_memory(session.id, settings=settings, reason="compaction")
```
- [ ] **Step 4 测试**:`scan_idle_and_extract` 只挑空闲+够轮次的会话(monkeypatch `extract_session_memory` 记录被调的 sid);`compact` 调用提炼且在折叠前。
- [ ] **Step 5 跑** → PASS
- [ ] **Step 6 提交**:`git commit -am "feat(backend): trigger memory extraction on idle scan + before compaction"`

---

## Task 8:注入 — assemble 改取当前块

**Files:** Modify `turn/assemble.py`;Test `tests/test_assemble.py`(追加)

- [ ] **Step 1 失败测试**:写两版 user 块,assemble 只注入最新一版(且只 1 条 user Mem)。
- [ ] **Step 2 改 assemble.py**(把 36-37 + 70 行的 `list_for_context` 换成 `get_current`):
```python
    mem_repo = MemoryEntryRepository(db)
    blocks = [b for b in (await mem_repo.get_current("user", session.user_id),
                          await mem_repo.get_current("agent", session.agent_config_id)) if b and b.content.strip()]
    # ...
        memory=[worker_pb2.Mem(scope=b.scope, content=b.content) for b in blocks],
```
- [ ] **Step 3 跑** → PASS(并确认现有 assemble 测试不回归)
- [ ] **Step 4 提交**:`git commit -am "feat(backend): inject current memory block (latest version) instead of recent-N"`

---

## Task 9:API — 当前块 GET/PUT/DELETE

**Files:** Modify `api/memory_entries.py`、`schemas/memory_entry.py`、`repositories/memory_entry.py`(清理旧 append/list);Test `tests/test_memory_api.py`(重写)

- [ ] **Step 1 schema**:
```python
class MemoryBlockRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    scope: str; owner_id: uuid.UUID; content: str; version: int
class MemoryBlockWrite(BaseModel):
    scope: str; agent_id: uuid.UUID | None = None; content: str
```
- [ ] **Step 2 失败测试**:PUT 写块 → GET 取回;跨租户 agent_id → 404;DELETE → GET 返回空块。
- [ ] **Step 3 实现**:`GET ?scope=&agent_id=` → `get_current`(无则返回 content="");`PUT` → 解析 owner(`resolve_owner`)、`get_current` 取 expected_version、`write_version`;`DELETE` → 写空块新版本。删掉旧 `POST append` 与 repo 的 `append`/`list_for_context`(确认 assemble 已不用)。
- [ ] **Step 4 跑** → PASS
- [ ] **Step 5 提交**:`git commit -am "feat(backend): memory block API (GET/PUT/DELETE current block)"`

---

## Task 10:前端 — 记忆查看/编辑/清空

**Files:** Modify `frontend/src/api/client.ts`、`types.ts`;Create `frontend/src/components/settings/MemoryPanel.tsx`;接进设置抽屉(user 块在账户/全局、agent 块在 agent 设置);Test `MemoryPanel.test.tsx`

- [ ] **Step 1 api**:`getMemory(scope, agentId?)` / `putMemory(scope, content, agentId?)` / `clearMemory(...)`。
- [ ] **Step 2 失败测试**:渲染当前块文本;编辑后点保存调用 `putMemory`;清空调用 `clearMemory`。
- [ ] **Step 3 组件**:`Textarea`(复用 ui)+ 保存/清空 `Button`;只读展示 version。user 块挂在设置抽屉新「记忆」处或账户;agent 块加到 AgentSettings 编辑器(标注"这是学到的记忆,≠ 指令/人设")。
- [ ] **Step 4 跑**:`cd frontend && npm run lint && npm test` → PASS
- [ ] **Step 5 提交**:`git commit -am "feat(frontend): memory panel — view/edit/clear memory block"`

---

## Task 11:全量回归 + 对抗审查

- [ ] **Step 1 回归**:
  - 后端:`cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker"`
  - worker:`cd services/worker && uv run pytest`
  - 前端:`cd frontend && npm run lint && npm test`
  - `uv run ruff check .`
- [ ] **Step 2 对抗审查**(子 agent,Opus,diff 内联):重点查——并发写丢更新/水位线竞态、reconcile 解析健壮性(模型乱输出)、空闲扫描会不会重复提炼/打爆 worker、key 是否仅经 worker、迁移回填正确性、注入空块不塞空段。
- [ ] **Step 3 修复**审查问题并重跑回归。
- [ ] **Step 4 收尾**:用 superpowers:finishing-a-development-branch。

---

## 自查(写完计划即时核对)

- **spec 覆盖**:写入(T5/6)、触发双路+轮次闸(T7)、单块+版本+并发(T3/4)、软上限(T5)、注入切换(T8)、UI(T10)、user 层 only(T5)——均有任务。✓
- **类型一致**:`get_current`/`write_version(expected_version=)`/`MemoryConflict`/`extract_session_memory(reason=)`/`ExtractMemoryRequest(soft_max_chars)` 跨任务一致。✓
- **待实现时核对**:`provider.complete` 真实签名、`session_scope`/`_channel`/`_msg_from_proto` 现有用法、`_idle_session_ids` 查询(status/last_active_at)——实现前先看对应文件照搬。
