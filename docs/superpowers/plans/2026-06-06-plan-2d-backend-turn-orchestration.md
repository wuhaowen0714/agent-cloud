# Plan 2d: 后端回合编排(端到端非流式回合) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让后端把"一个回合"端到端跑通(非流式):接收用户消息 → 会话锁(串行)→ 从 DB 组装上下文 → gRPC 调 worker `RunTurn` → 落库新消息 → 释放锁 → 返回。打通 前端API→后端→worker→沙箱→DB 全链路。

**Architecture:** 后端新增 `turn/` 模块:`worker_client`(gRPC 调 worker)、`messages`(ORM Message↔common Message 转换)、`assemble`(从仓库组装 `RunTurnRequest`)。`SessionRepository` 加原子会话锁(`UPDATE ... WHERE status='idle'`)。新增 `POST /sessions/{id}/turn` 端点编排整个流程。仍用 FakeProvider(经 worker 注入);**单个配置的沙箱端点**(每用户 sandbox 生命周期/路由 = Plan 4)。

**Tech Stack:** Python 3.12+、FastAPI、SQLAlchemy async、grpcio、pytest + testcontainers(真 Postgres)+ pytest-asyncio。e2e 起真 sandbox + 真 worker(FakeProvider)+ 后端 + 真库。

参考:spec `docs/superpowers/specs/2026-06-05-stateless-agent-cloud-design.md`(§5 数据模型、§7 契约、§8 回合生命周期、§10 失败处理)。已合并:Plan 1(后端数据层/仓库)、2a(run_turn)、2b(沙箱)、2c(worker `RunTurn` 服务器 + common `codec` + `MAX_GRPC_MESSAGE_BYTES`)。

## 范围

**做**:会话锁(repo)、ORM↔common 消息转换、上下文组装、worker gRPC 客户端、`POST /sessions/{id}/turn` 端点、单元测试(假 worker)+ 全链路 e2e(真 sandbox+worker+DB)。

**不做(后续)**:每用户 sandbox 生命周期/路由(Plan 4,本计划用单一配置端点)、skills 注入(Plan 5,本计划传空)、真实 LLM provider、流式(Plan 3)、auth。

## 关键编排顺序(spec §8,含一处更合理的调整)

1. 取 session(不存在→404)。
2. **先加会话锁**(`try_acquire`:`status` idle→running 原子);失败→409(并发被拒,**不落任何东西**)。
   - (这比 spec §8"先持久化 user 消息再加锁"更合理:被拒时不会留下孤立 user 消息。)
3. 持久化 user 消息(commit)。
4. 组装上下文(历史**不含**刚写的 user 消息;它作为 `user_message` 单独传)→ 调 worker `RunTurn`。
5. 落库 `new_messages`(commit)。
6. **finally** 释放锁(commit)。worker 失败 → 该回合失败(user 消息已落、assistant 未落),返回 502,用户可重试(尽力而为 §10)。

## File Structure

```
services/backend/
  pyproject.toml                          # +grpcio
  src/agent_cloud_backend/
    config.py                             # +worker_endpoint, +sandbox_endpoint
    repositories/session.py               # +try_acquire / +release
    turn/__init__.py
    turn/messages.py                      # orm_to_common / common_to_content
    turn/worker_client.py                 # run_turn_via_worker(endpoint, request)
    turn/assemble.py                      # build_run_turn_request(...)
    schemas/turn.py                       # TurnRequest / TurnResponse
    api/turn.py                           # POST /sessions/{id}/turn
    main.py                               # include turn router
  tests/
    test_session_lock.py
    test_turn_messages.py
    test_assemble.py
    test_turn_endpoint.py                 # 单元:monkeypatch 假 worker
    test_turn_e2e.py                      # 全链路:真 sandbox+worker(FakeProvider)+DB
```

---

### Task 0: 后端 gRPC 依赖 + 配置 + worker 客户端

**Files:**
- Modify: `services/backend/pyproject.toml`, `services/backend/src/agent_cloud_backend/config.py`
- Create: `services/backend/src/agent_cloud_backend/turn/__init__.py`, `services/backend/src/agent_cloud_backend/turn/worker_client.py`

- [ ] **Step 1: 加 grpcio 依赖**

Edit `services/backend/pyproject.toml`: `[project].dependencies` 加 `"grpcio"`(common 已带 protobuf + 生成桩)。

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud && uv sync`

- [ ] **Step 2: 配置加 worker/sandbox 端点**

Edit `services/backend/src/agent_cloud_backend/config.py` 的 `Settings`,加两个字段:
```python
    worker_endpoint: str = "localhost:50052"
    sandbox_endpoint: str = "localhost:50051"
```

- [ ] **Step 3: 写 worker 客户端**

Create `services/backend/src/agent_cloud_backend/turn/__init__.py`(空)。

Create `services/backend/src/agent_cloud_backend/turn/worker_client.py`:
```python
from __future__ import annotations

import grpc

from agent_cloud.v1 import worker_pb2, worker_pb2_grpc
from agent_cloud_common import MAX_GRPC_MESSAGE_BYTES


async def run_turn_via_worker(
    worker_endpoint: str, request: worker_pb2.RunTurnRequest
) -> worker_pb2.RunTurnResponse:
    """向 worker 发起一次 RunTurn(一元)。消息上限与 worker 端一致。"""
    options = [
        ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
        ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
    ]
    async with grpc.aio.insecure_channel(worker_endpoint, options=options) as channel:
        stub = worker_pb2_grpc.WorkerStub(channel)
        return await stub.RunTurn(request)
```

- [ ] **Step 4: 提交**

```bash
git add services/backend/pyproject.toml services/backend/src/agent_cloud_backend/config.py services/backend/src/agent_cloud_backend/turn/__init__.py services/backend/src/agent_cloud_backend/turn/worker_client.py uv.lock
git commit -m "feat(backend): add grpc worker client and turn endpoints config"
```

---

### Task 1: 会话锁(SessionRepository)

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/repositories/session.py`
- Test: `services/backend/tests/test_session_lock.py`

- [ ] **Step 1: 写失败测试**

Create `services/backend/tests/test_session_lock.py`:
```python
from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.repositories.user import UserRepository


async def _session(session):
    user = await UserRepository(session).create(User(email="l@example.com"))
    await session.flush()
    agent = await AgentConfigRepository(session).create(
        AgentConfig(user_id=user.id, name="a", model="m", provider="p")
    )
    await session.flush()
    return await SessionRepository(session).create_for(user.id, agent.id, None)


async def test_acquire_then_reject_then_release(session):
    repo = SessionRepository(session)
    s = await _session(session)
    await session.commit()

    assert await repo.try_acquire(s.id) is True
    await session.commit()
    assert (await repo.get(s.id)).status == "running"

    # second acquire while running -> rejected
    assert await repo.try_acquire(s.id) is False

    await repo.release(s.id)
    await session.commit()
    assert (await repo.get(s.id)).status == "idle"

    # acquirable again after release
    assert await repo.try_acquire(s.id) is True
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_session_lock.py -v`
Expected: FAIL(`AttributeError: ... 'SessionRepository' object has no attribute 'try_acquire'`)。

- [ ] **Step 3: 实现锁**

Edit `services/backend/src/agent_cloud_backend/repositories/session.py`: add imports `from sqlalchemy import func, select, update` (select 已有则合并),并在类中加:
```python
    async def try_acquire(self, session_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            update(Session)
            .where(Session.id == session_id, Session.status == "idle")
            .values(status="running", last_active_at=func.now())
        )
        return result.rowcount == 1

    async def release(self, session_id: uuid.UUID) -> None:
        await self.session.execute(
            update(Session).where(Session.id == session_id).values(status="idle")
        )
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_session_lock.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add services/backend/src/agent_cloud_backend/repositories/session.py services/backend/tests/test_session_lock.py
git commit -m "feat(backend): add atomic session lock (try_acquire/release)"
```

---

### Task 2: ORM Message ↔ common Message 转换

**Files:**
- Create: `services/backend/src/agent_cloud_backend/turn/messages.py`
- Test: `services/backend/tests/test_turn_messages.py`

- [ ] **Step 1: 写失败测试**

Create `services/backend/tests/test_turn_messages.py`:
```python
from agent_cloud_backend.models.message import Message as OrmMessage
from agent_cloud_backend.turn.messages import common_to_content, orm_to_common
from agent_cloud_common import Message as CommonMessage
from agent_cloud_common import Role, ToolCall, ToolResult


def test_orm_to_common_assistant_with_tool_calls():
    orm = OrmMessage(session_id=None, seq=0, role="assistant",
                     content={"text": "hi",
                              "tool_calls": [{"id": "c1", "name": "bash",
                                              "arguments": {"command": "echo x"}}],
                              "tool_results": []})
    cm = orm_to_common(orm)
    assert cm.role == Role.ASSISTANT and cm.text == "hi"
    assert cm.tool_calls[0].name == "bash"
    assert cm.tool_calls[0].arguments == {"command": "echo x"}


def test_common_to_content_round_trip():
    cm = CommonMessage(role=Role.TOOL,
                       tool_results=[ToolResult(call_id="c1", content="out", is_error=False)])
    content = common_to_content(cm)
    assert content == {"text": "", "tool_calls": [],
                       "tool_results": [{"call_id": "c1", "content": "out", "is_error": False}]}
    # round trip through orm shape
    back = orm_to_common(OrmMessage(session_id=None, seq=0, role="tool", content=content))
    assert back.tool_results[0].call_id == "c1" and back.tool_results[0].is_error is False


def test_orm_to_common_tolerates_missing_keys():
    cm = orm_to_common(OrmMessage(session_id=None, seq=0, role="user", content={"text": "hello"}))
    assert cm.role == Role.USER and cm.text == "hello"
    assert cm.tool_calls == [] and cm.tool_results == []
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_turn_messages.py -v`
Expected: FAIL(`ModuleNotFoundError: agent_cloud_backend.turn.messages`)。

- [ ] **Step 3: 实现转换**

Create `services/backend/src/agent_cloud_backend/turn/messages.py`:
```python
from __future__ import annotations

from agent_cloud_backend.models.message import Message as OrmMessage
from agent_cloud_common import Message as CommonMessage
from agent_cloud_common import Role, ToolCall, ToolResult


def orm_to_common(message: OrmMessage) -> CommonMessage:
    content = message.content or {}
    return CommonMessage(
        role=Role(message.role),
        text=content.get("text", ""),
        tool_calls=[ToolCall(**c) for c in content.get("tool_calls", [])],
        tool_results=[ToolResult(**r) for r in content.get("tool_results", [])],
    )


def common_to_content(message: CommonMessage) -> dict:
    return {
        "text": message.text,
        "tool_calls": [
            {"id": c.id, "name": c.name, "arguments": c.arguments} for c in message.tool_calls
        ],
        "tool_results": [
            {"call_id": r.call_id, "content": r.content, "is_error": r.is_error}
            for r in message.tool_results
        ],
    }
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_turn_messages.py -v`
Expected: PASS(3 passed)。

- [ ] **Step 5: 提交**

```bash
git add services/backend/src/agent_cloud_backend/turn/messages.py services/backend/tests/test_turn_messages.py
git commit -m "feat(backend): add ORM<->common message conversion"
```

---

### Task 3: 上下文组装(build_run_turn_request)

**Files:**
- Create: `services/backend/src/agent_cloud_backend/turn/assemble.py`
- Test: `services/backend/tests/test_assemble.py`

- [ ] **Step 1: 写失败测试**

Create `services/backend/tests/test_assemble.py`:
```python
from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.message import Message as OrmMessage
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.context_document import ContextDocumentRepository
from agent_cloud_backend.repositories.memory_entry import MemoryEntryRepository
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.repositories.user import UserRepository
from agent_cloud_backend.turn.assemble import build_run_turn_request


async def test_build_request_from_db(session):
    user = await UserRepository(session).create(User(email="a@example.com"))
    await session.flush()
    agent = await AgentConfigRepository(session).create(
        AgentConfig(user_id=user.id, name="coder", model="claude-x", provider="anthropic",
                    enabled_tools=["bash"])
    )
    await session.flush()
    s = await SessionRepository(session).create_for(user.id, agent.id, None)
    await session.flush()
    await ContextDocumentRepository(session).upsert("user", "USER", user.id, "# user")
    await ContextDocumentRepository(session).upsert("agent", "AGENTS", agent.id, "# agent")
    await MemoryEntryRepository(session).append("user", user.id, "likes tea")
    # history: one prior user message (NOT the current turn's)
    prior = await MessageRepository(session).append(
        s.id, OrmMessage(session_id=s.id, seq=0, role="user", content={"text": "earlier"}))
    await session.commit()

    req = await build_run_turn_request(
        session, s, sandbox_endpoint="localhost:50051",
        user_message="now", exclude_message_id=None,
    )
    assert req.session_id == str(s.id) and req.user_id == str(user.id)
    assert req.agent.model == "claude-x" and list(req.agent.enabled_tools) == ["bash"]
    assert {d.type for d in req.documents} == {"USER", "AGENTS"}
    assert any(m.content == "likes tea" for m in req.memory)
    assert [m.text for m in req.messages] == ["earlier"]   # history
    assert req.user_message == "now"
    assert req.sandbox_endpoint == "localhost:50051"
    assert req.work_subdir == s.work_subdir


async def test_build_request_excludes_current_user_message(session):
    user = await UserRepository(session).create(User(email="b@example.com"))
    await session.flush()
    agent = await AgentConfigRepository(session).create(
        AgentConfig(user_id=user.id, name="c", model="m", provider="p"))
    await session.flush()
    s = await SessionRepository(session).create_for(user.id, agent.id, None)
    await session.flush()
    current = await MessageRepository(session).append(
        s.id, OrmMessage(session_id=s.id, seq=0, role="user", content={"text": "current"}))
    await session.commit()
    req = await build_run_turn_request(
        session, s, sandbox_endpoint="x", user_message="current",
        exclude_message_id=current.id,
    )
    assert req.messages == []  # the only message was excluded
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_assemble.py -v`
Expected: FAIL(`ModuleNotFoundError: agent_cloud_backend.turn.assemble`)。

- [ ] **Step 3: 实现组装**

Create `services/backend/src/agent_cloud_backend/turn/assemble.py`:
```python
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud.v1 import worker_pb2
from agent_cloud_common.codec import msg_to_proto

from agent_cloud_backend.models.session import Session
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.context_document import ContextDocumentRepository
from agent_cloud_backend.repositories.memory_entry import MemoryEntryRepository
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.turn.messages import orm_to_common


async def build_run_turn_request(
    db: AsyncSession,
    session: Session,
    *,
    sandbox_endpoint: str,
    user_message: str,
    exclude_message_id: uuid.UUID | None,
) -> worker_pb2.RunTurnRequest:
    agent = await AgentConfigRepository(db).get(session.agent_config_id)
    doc_repo = ContextDocumentRepository(db)
    user_docs = await doc_repo.list_for_owner("user", session.user_id)
    agent_docs = await doc_repo.list_for_owner("agent", session.agent_config_id)
    mem_repo = MemoryEntryRepository(db)
    user_mem = await mem_repo.list_for_context("user", session.user_id)
    agent_mem = await mem_repo.list_for_context("agent", session.agent_config_id)
    history = await MessageRepository(db).list_by_session(session.id)
    history = [m for m in history if m.id != exclude_message_id]

    return worker_pb2.RunTurnRequest(
        session_id=str(session.id),
        user_id=str(session.user_id),
        agent=worker_pb2.Agent(
            model=agent.model,
            provider=agent.provider,
            thinking_level=agent.thinking_level or "",
            enabled_tools=list(agent.enabled_tools),
            key_ref=agent.key_ref or "",
        ),
        documents=[
            worker_pb2.Doc(scope=d.scope, type=d.type, content=d.content)
            for d in [*user_docs, *agent_docs]
        ],
        memory=[worker_pb2.Mem(scope=e.scope, content=e.content) for e in [*user_mem, *agent_mem]],
        skills=[],  # Plan 5
        messages=[msg_to_proto(orm_to_common(m)) for m in history],
        user_message=user_message,
        sandbox_endpoint=sandbox_endpoint,
        work_subdir=session.work_subdir,
    )
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_assemble.py -v`
Expected: PASS(2 passed)。

- [ ] **Step 5: 提交**

```bash
git add services/backend/src/agent_cloud_backend/turn/assemble.py services/backend/tests/test_assemble.py
git commit -m "feat(backend): assemble RunTurnRequest from DB context"
```

---

### Task 4: 回合端点(编排)+ 单元测试(假 worker)

**Files:**
- Create: `services/backend/src/agent_cloud_backend/schemas/turn.py`, `services/backend/src/agent_cloud_backend/api/turn.py`
- Modify: `services/backend/src/agent_cloud_backend/main.py`
- Test: `services/backend/tests/test_turn_endpoint.py`

- [ ] **Step 1: 写 schemas**

Create `services/backend/src/agent_cloud_backend/schemas/turn.py`:
```python
from pydantic import BaseModel

from agent_cloud_backend.schemas.message import MessageRead


class TurnRequest(BaseModel):
    content: str


class TurnUsage(BaseModel):
    input_tokens: int
    output_tokens: int


class TurnResponse(BaseModel):
    messages: list[MessageRead]   # 本回合新增的 assistant/tool 消息
    stop_reason: str
    usage: TurnUsage
```

- [ ] **Step 2: 写失败测试(单元:monkeypatch 假 worker)**

Create `services/backend/tests/test_turn_endpoint.py`:
```python
import uuid

import pytest

from agent_cloud.v1 import worker_pb2


@pytest.fixture
def fake_worker(monkeypatch):
    """让端点不真正连 worker:返回脚本化的 RunTurnResponse。"""
    captured = {}

    async def _fake(worker_endpoint, request):
        captured["request"] = request
        return worker_pb2.RunTurnResponse(
            new_messages=[
                worker_pb2.Msg(role="assistant", text="", tool_calls=[
                    worker_pb2.ToolCall(id="c1", name="bash", arguments_json='{"command": "echo hi"}')]),
                worker_pb2.Msg(role="tool", tool_results=[
                    worker_pb2.ToolResult(call_id="c1", content="hi\n", is_error=False)]),
                worker_pb2.Msg(role="assistant", text="done"),
            ],
            input_tokens=5, output_tokens=7, stop_reason="end_turn",
        )

    from agent_cloud_backend.api import turn as turn_module
    monkeypatch.setattr(turn_module, "run_turn_via_worker", _fake)
    return captured


async def _make_session(client):
    uid = (await client.post("/users", json={"email": "t@example.com"})).json()["id"]
    aid = (await client.post("/agent-configs",
           json={"user_id": uid, "name": "c", "model": "m", "provider": "p"})).json()["id"]
    sid = (await client.post("/sessions", json={"user_id": uid, "agent_config_id": aid})).json()["id"]
    return sid


async def test_turn_persists_and_returns(client, fake_worker):
    sid = await _make_session(client)
    r = await client.post(f"/sessions/{sid}/turn", json={"content": "say hi"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stop_reason"] == "end_turn"
    assert [m["role"] for m in body["messages"]] == ["assistant", "tool", "assistant"]
    assert body["usage"]["output_tokens"] == 7
    # user message + 3 new persisted, in order
    listed = (await client.get(f"/sessions/{sid}/messages")).json()
    assert [m["role"] for m in listed] == ["user", "assistant", "tool", "assistant"]
    # assembled request carried the user message + work_subdir
    assert fake_worker["request"].user_message == "say hi"
    assert fake_worker["request"].work_subdir == f"sessions/{sid}"


async def test_turn_releases_lock_so_second_turn_works(client, fake_worker):
    sid = await _make_session(client)
    assert (await client.post(f"/sessions/{sid}/turn", json={"content": "one"})).status_code == 200
    assert (await client.post(f"/sessions/{sid}/turn", json={"content": "two"})).status_code == 200


async def test_turn_on_missing_session_404(client, fake_worker):
    r = await client.post(f"/sessions/{uuid.uuid4()}/turn", json={"content": "x"})
    assert r.status_code == 404
```

- [ ] **Step 3: 运行,确认失败**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_turn_endpoint.py -v`
Expected: FAIL(端点不存在 → 404 for the turn path / import error)。

- [ ] **Step 4: 写端点**

Create `services/backend/src/agent_cloud_backend/api/turn.py`:
```python
from __future__ import annotations

import uuid

import grpc
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.schemas.turn import TurnRequest, TurnResponse, TurnUsage
from agent_cloud_backend.turn.assemble import build_run_turn_request
from agent_cloud_backend.turn.messages import common_to_content
from agent_cloud_backend.turn.worker_client import run_turn_via_worker
from agent_cloud_common.codec import msg_from_proto

router = APIRouter(prefix="/sessions/{session_id}/turn", tags=["turn"])


@router.post("", response_model=TurnResponse)
async def run_turn_endpoint(
    session_id: uuid.UUID,
    body: TurnRequest,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    session_repo = SessionRepository(db)
    msg_repo = MessageRepository(db)

    s = await session_repo.get(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")

    # 1. 加锁(失败=并发,拒绝;不落任何东西)
    if not await session_repo.try_acquire(session_id):
        await db.rollback()
        raise HTTPException(status_code=409, detail="session is busy")
    await db.commit()

    try:
        # 2. 持久化 user 消息
        user_msg = await msg_repo.append(
            session_id,
            Message(session_id=session_id, seq=0, role="user",
                    content={"text": body.content, "tool_calls": [], "tool_results": []}),
        )
        await db.commit()

        # 3. 组装 + 调 worker
        request = await build_run_turn_request(
            db, s, sandbox_endpoint=settings.sandbox_endpoint,
            user_message=body.content, exclude_message_id=user_msg.id,
        )
        try:
            response = await run_turn_via_worker(settings.worker_endpoint, request)
        except grpc.aio.AioRpcError as exc:
            raise HTTPException(status_code=502, detail=f"worker unavailable: {exc.code().name}")

        # 4. 落库新消息
        persisted = []
        for proto_msg in response.new_messages:
            common = msg_from_proto(proto_msg)
            row = await msg_repo.append(
                session_id,
                Message(session_id=session_id, seq=0, role=common.role.value,
                        content=common_to_content(common)),
            )
            persisted.append(row)
        await db.commit()

        return TurnResponse(
            messages=persisted,
            stop_reason=response.stop_reason,
            usage=TurnUsage(input_tokens=response.input_tokens,
                            output_tokens=response.output_tokens),
        )
    finally:
        # 5. 释放锁
        await session_repo.release(session_id)
        await db.commit()
```

> Note: `get_settings` is imported from config; the e2e test (Task 5) overrides it via `app.dependency_overrides[get_settings]`. Ensure `config.get_settings` exists (Plan 1 defined it).

- [ ] **Step 5: 挂载路由**

Edit `services/backend/src/agent_cloud_backend/main.py`: import `turn` and include its router (add to the module tuple in `create_app`):
```python
from agent_cloud_backend.api import (
    agent_configs, context_documents, memory_entries, messages, sessions, turn, users,
)
# ...
    for module in (users, agent_configs, sessions, messages, context_documents, memory_entries, turn):
        app.include_router(module.router)
```

- [ ] **Step 6: 运行,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_turn_endpoint.py -v`
Expected: PASS(3 passed)。

- [ ] **Step 7: 提交**

```bash
git add services/backend/src/agent_cloud_backend/schemas/turn.py services/backend/src/agent_cloud_backend/api/turn.py services/backend/src/agent_cloud_backend/main.py services/backend/tests/test_turn_endpoint.py
git commit -m "feat(backend): add turn endpoint orchestrating lock, assembly, worker call, persist"
```

---

### Task 5: 全链路 e2e(真 sandbox + worker + 后端 + DB)

**Files:**
- Test: `services/backend/tests/test_turn_e2e.py`
- Modify: `services/backend/pyproject.toml`(dev +agent-cloud-worker, +agent-cloud-sandbox)

- [ ] **Step 1: 后端 dev 依赖加 worker/sandbox(仅 e2e 用)**

Edit `services/backend/pyproject.toml`:
- `[dependency-groups].dev` 加 `"agent-cloud-worker"`、`"agent-cloud-sandbox"`。
- `[tool.uv.sources]` 加 `agent-cloud-worker = { workspace = true }`、`agent-cloud-sandbox = { workspace = true }`。

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud && uv sync`

- [ ] **Step 2: 写 e2e 测试**

Create `services/backend/tests/test_turn_e2e.py`:
```python
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.main import create_app
from agent_cloud_common import CompletionResult, Message, Role, ToolCall, Usage
from agent_cloud_sandbox.server import create_server as create_sandbox_server
from agent_cloud_worker.provider import FakeProvider
from agent_cloud_worker.server import create_server as create_worker_server


@pytest_asyncio.fixture
async def stack(engine, tmp_path):
    # 真沙箱
    sandbox_server, sport = await create_sandbox_server(base_workdir=tmp_path, port=0)
    # 真 worker(FakeProvider:写文件再收尾)
    provider = FakeProvider([
        CompletionResult(message=Message(role=Role.ASSISTANT, tool_calls=[
            ToolCall(id="c1", name="write_file",
                     arguments={"path": "hello.txt", "content": "from-agent"})]),
            usage=Usage(input_tokens=2, output_tokens=3)),
        CompletionResult(message=Message(role=Role.ASSISTANT, text="done"),
                         usage=Usage(input_tokens=2, output_tokens=3)),
    ])
    worker_server, wport = await create_worker_server(
        provider_factory=lambda *a: provider, port=0)

    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_session():
        async with maker() as sdb:
            yield sdb

    def _override_settings():
        return Settings(worker_endpoint=f"localhost:{wport}",
                        sandbox_endpoint=f"localhost:{sport}")

    app = create_app()
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_settings] = _override_settings
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, tmp_path
    await worker_server.stop(None)
    await sandbox_server.stop(None)


async def test_full_turn_through_all_layers(stack):
    client, base = stack
    uid = (await client.post("/users", json={"email": "e2e@example.com"})).json()["id"]
    aid = (await client.post("/agent-configs",
           json={"user_id": uid, "name": "coder", "model": "m", "provider": "fake"})).json()["id"]
    sid = (await client.post("/sessions",
           json={"user_id": uid, "agent_config_id": aid})).json()["id"]

    r = await client.post(f"/sessions/{sid}/turn", json={"content": "write the file"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stop_reason"] == "end_turn"
    assert [m["role"] for m in body["messages"]] == ["assistant", "tool", "assistant"]

    # 工具真的在沙箱里执行了(work_subdir = sessions/{sid})
    assert (base / f"sessions/{sid}" / "hello.txt").read_text() == "from-agent"

    # DB 落了 user + assistant + tool + assistant
    listed = (await client.get(f"/sessions/{sid}/messages")).json()
    assert [m["role"] for m in listed] == ["user", "assistant", "tool", "assistant"]
```

- [ ] **Step 3: 运行,确认通过**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest tests/test_turn_e2e.py -v`
Expected: PASS(1 passed)。需 Docker(testcontainers Postgres);worker/sandbox 为进程内 aio 服务器。

- [ ] **Step 4: 提交**

```bash
git add services/backend/pyproject.toml services/backend/tests/test_turn_e2e.py uv.lock
git commit -m "test(backend): full non-streaming turn e2e through sandbox+worker+db"
```

---

### Task 6: lint + README + 全回归

**Files:**
- Modify: `services/backend/README.md`

- [ ] **Step 1: lint**

Run: `cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run ruff check --fix . && uv run ruff format .`
Expected: clean。

- [ ] **Step 2: README 追加**

在 `services/backend/README.md` 末尾追加:
```markdown

## 回合编排(Plan 2d)
- `POST /sessions/{id}/turn` `{ "content": "..." }` → 加会话锁 → 组装上下文 → gRPC 调 worker `RunTurn` → 落库新消息 → 返回 `{messages, stop_reason, usage}`。
- 配置:`AGENT_CLOUD_WORKER_ENDPOINT`、`AGENT_CLOUD_SANDBOX_ENDPOINT`(默认 localhost:50052 / 50051)。
- 当前为单一配置沙箱端点;每用户 sandbox 生命周期/路由见 Plan 4。流式见 Plan 3。
```

- [ ] **Step 3: 全回归**

Run(四套):
```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud/packages/common && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/sandbox && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker && uv run pytest -q
cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend && uv run pytest -q
```
Expected:common 4;sandbox 23;worker 38;backend 35(25 + 本计划 lock 1 + messages 3 + assemble 2 + endpoint 3 + e2e 1 = 35)。

- [ ] **Step 4: 提交**

```bash
git add services/backend/README.md
git commit -m "chore(backend): document turn endpoint"
```

---

## Self-Review(写完后自检结果)

**Spec 覆盖(Plan 2d 范围)**:
- §8 回合生命周期(锁→持久化 user→组装→调 worker→落新消息→释放锁)→ `api/turn.py`(锁先于持久化,见上文调整说明)。✓
- §5 会话内串行锁(`status`)→ `SessionRepository.try_acquire/release`(原子 `UPDATE ... WHERE status='idle'`)。✓
- §5.3 上下文组装(用户级+agent级 文档/记忆 + 历史)→ `build_run_turn_request`;skills 传空(Plan 5)。✓
- §7 契约:后端构造 `RunTurnRequest`、消费 `RunTurnResponse`(经 common codec + ORM 转换)。✓
- §10 失败处理:worker 不可达→502 + 锁在 finally 释放;user 消息已落、assistant 未落,可重试。✓
- 简化(已注明):单一配置沙箱端点(Plan 4 做每用户路由);真实 provider/流式后续。

**占位符扫描**:无 TBD;每步有完整代码或确切命令/预期。

**类型/命名一致性**:`try_acquire/release` 在 repo 定义、端点引用一致;`orm_to_common/common_to_content` 在 messages.py 定义、assemble/endpoint 引用;`build_run_turn_request(db, session, *, sandbox_endpoint, user_message, exclude_message_id)` 签名在测试与实现一致;`run_turn_via_worker(worker_endpoint, request)` 一致;复用 2c 的 `worker_pb2`/`msg_to_proto`/`msg_from_proto`/`MAX_GRPC_MESSAGE_BYTES`、2c worker `create_server(provider_factory, host, port)`、2b sandbox `create_server(base_workdir, host, port)`;端点经 `get_settings` 依赖,e2e 用 `app.dependency_overrides[get_settings]` 覆盖。
```
