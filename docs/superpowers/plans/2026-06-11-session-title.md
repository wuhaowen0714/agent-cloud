# 会话标题自动生成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 首条提问后由 LLM 自动生成 ≤16 字会话标题;手动改名永不覆盖。

**Architecture:** worker 新一元 RPC `GenerateTitle`(镜像 Summarize:同 provider 工厂、非流式 complete、worker 侧清洗);backend 在两条 turn 成功路径(api/turn.py 一元、turn/runner.py 流式)收尾后 fire-and-forget `generate_session_title` 钩子(独立 DB 会话、写前二次检查、全程吞异常);前端首回合结束后延迟 3s 二次 invalidate sessions。

**Tech Stack:** gRPC proto + FastAPI + pytest;React Query + vitest。

参考 spec:`docs/superpowers/specs/2026-06-11-session-title-design.md`(f5d56f2)

注:spec 里「runner 判 title is None 再 spawn」落地为:**端点侧**(已载 session 行)做廉价预判传入/直判,钩子内首步再权威复查——语义同,省 runner 的额外查询。

---

## Task ST-1: proto + worker GenerateTitle(TDD)

**Files:**
- Modify: `protos/agent_cloud/v1/worker.proto`(service + 两 message)
- Create: `services/worker/src/agent_cloud_worker/title.py`(`TITLE_SYSTEM`、`_clean_title`)
- Modify: `services/worker/src/agent_cloud_worker/server.py`(handler,镜像 Summarize)
- Test: `services/worker/tests/test_title.py`(清洗纯函数)+ server 测试文件中 GenerateTitle 用例(镜像既有 Summarize 测试的构造方式)

- [ ] proto 追加并重生成(`bash scripts/gen_protos.sh`):

```proto
// 会话标题:基于首条用户提问起 ≤16 字短名(backend 回合后异步调用)。
message GenerateTitleRequest {
  Agent agent = 1;
  string user_message = 2;
}
message GenerateTitleResponse {
  string title = 1;
  int64 input_tokens = 2;
  int64 output_tokens = 3;
}
```

service 加 `rpc GenerateTitle(GenerateTitleRequest) returns (GenerateTitleResponse);`

- [ ] **失败测试**(test_title.py:`_clean_title` —— 成对引号/换行压缩/50 字符截 47+`…`/全空白→"";server 用例:fake provider 返回 `"「快排实现」\n"` → resp.title == "快排实现";空 user_message → INVALID_ARGUMENT;provider 工厂炸 → FAILED_PRECONDITION)
- [ ] **实现** — `title.py`:

```python
TITLE_SYSTEM = (
    "为下面这条用户消息起一个简短的会话标题。要求:不超过 16 个字;"
    "直接输出标题本身;不要引号、句号或任何解释。"
)
_QUOTES = [("\"", "\""), ("'", "'"), ("“", "”"), ("‘", "’"), ("「", "」"), ("『", "』")]


def clean_title(raw: str) -> str:
    """LLM 输出 → 可入库标题:压空白、剥成对引号、截 50 字符;清不出东西返回 ""。"""
    t = " ".join(raw.split())
    for left, right in _QUOTES:
        if len(t) >= 2 and t.startswith(left) and t.endswith(right):
            t = t[1:-1].strip()
    if len(t) > 50:
        t = t[:47] + "…"
    return t
```

server.py handler(镜像 Summarize 的工厂/异常收敛;`request.user_message` 截前 2000 字符进 prompt;`complete()` 后 `clean_title`;空输入 abort INVALID_ARGUMENT):

```python
    async def GenerateTitle(
        self, request: worker_pb2.GenerateTitleRequest, context: grpc.aio.ServicerContext
    ) -> worker_pb2.GenerateTitleResponse:
        # 基于首条用户提问起短名。一次小 LLM 调用,不用工具;清洗在 worker 侧。
        text = request.user_message.strip()
        if not text:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "empty user_message")
            return
        try:
            provider = self._provider_factory(
                request.agent.model, request.agent.provider,
                request.agent.api_key, request.agent.base_url,
            )
        except Exception as exc:  # noqa: BLE001 — 同 Summarize:工厂任意失败收敛为状态码
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, f"provider unavailable: {exc}")
            return
        try:
            result = await provider.complete(CompletionRequest(
                system=TITLE_SYSTEM,
                messages=[Message(role=Role.USER, text=text[:2000])],
                tools=[],
            ))
        except Exception:
            logger.exception("GenerateTitle failed")
            await context.abort(grpc.StatusCode.INTERNAL, "title generation failed")
            return
        return worker_pb2.GenerateTitleResponse(
            title=clean_title(result.message.text),
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
        )
```

- [ ] Run: `cd services/worker && uv run pytest -q` → 全 PASS;提交 `feat(worker): GenerateTitle RPC — short session titles from the first question`

## Task ST-2: backend 客户端 + 标题钩子(TDD)

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/turn/worker_client.py`
- Create: `services/backend/src/agent_cloud_backend/turn/title.py`
- Test: `services/backend/tests/test_session_title.py`(钩子单测,monkeypatch `generate_title_via_worker`,DB 走既有 conftest;镜像 memory_extract 测试的取数/建会话方式)

- [ ] **失败测试**:成功写入(title null + 有首条 user 消息 → 钩子后 title == 假标题);已有 title 不调 worker(spy 断言零调用);**写前竞态**(假 worker 函数在返回前把 session.title 改成 "手动名" → 钩子不覆盖);worker 抛 AioRpcError → title 留 null 且不抛;清洗后空串 → 不写。
- [ ] **实现** — worker_client.py 追加(同既有函数的 options/channel 模式):

```python
async def generate_title_via_worker(
    worker_endpoint: str, request: worker_pb2.GenerateTitleRequest
) -> str:
    """向 worker 发起一次 GenerateTitle(基于首条提问起短名),返回清洗后的标题。"""
    options = [
        ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
        ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
    ]
    async with grpc.aio.insecure_channel(worker_endpoint, options=options) as channel:
        resp = await worker_pb2_grpc.WorkerStub(channel).GenerateTitle(request)
        return resp.title
```

turn/title.py(独立 sessionmaker、双检查、吞异常;`_TITLE_TASKS` 持引用防 GC):

```python
from __future__ import annotations

import asyncio
import logging
import uuid

from agent_cloud.v1 import worker_pb2
from sqlalchemy import select

from agent_cloud_backend.config import Settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.turn.credentials import resolve_agent_key
from agent_cloud_backend.turn.worker_client import generate_title_via_worker

logger = logging.getLogger(__name__)

# fire-and-forget 任务持引用,防止被 GC 提前回收
_TITLE_TASKS: set[asyncio.Task] = set()


def spawn_title_generation(session_id: uuid.UUID, *, settings: Settings) -> None:
    """回合成功收尾后调用:异步生成会话标题,绝不阻塞/影响回合本身。"""
    task = asyncio.create_task(generate_session_title(session_id, settings=settings))
    _TITLE_TASKS.add(task)
    task.add_done_callback(_TITLE_TASKS.discard)


async def generate_session_title(session_id: uuid.UUID, *, settings: Settings) -> bool:
    """title 为空时,基于首条 user 消息让 LLM 起名(spec 2026-06-11)。

    best-effort:任何失败只记日志、留 null(下一回合自然重试);
    写前重查 title 仍为空才写——生成期间用户手动改名优先。
    返回是否写入。
    """
    try:
        async with get_sessionmaker()() as db:
            s = await db.get(Session, session_id)
            if s is None or s.title is not None:
                return False
            first = (
                await db.execute(
                    select(Message)
                    .where(Message.session_id == session_id, Message.role == "user")
                    .order_by(Message.seq)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if first is None:
                return False
            text = (first.content or {}).get("text", "")
            if not text.strip():
                return False
            agent = await AgentConfigRepository(db).get(s.agent_config_id)
            if agent is None:
                return False
            api_key, base_url = await resolve_agent_key(
                db, agent.key_ref or "", s.user_id, settings
            )
            title = await generate_title_via_worker(
                settings.worker_endpoint,
                worker_pb2.GenerateTitleRequest(
                    agent=worker_pb2.Agent(
                        model=agent.model, provider=agent.provider,
                        api_key=api_key, base_url=base_url,
                    ),
                    user_message=text,
                ),
            )
            if not title:
                return False
            await db.refresh(s)  # 写前重查:生成期间被手动改名 → 不覆盖
            if s.title is not None:
                return False
            s.title = title
            await db.commit()
            return True
    except Exception:
        logger.warning("session title generation failed for %s", session_id, exc_info=True)
        return False
```

- [ ] Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_session_title.py -q` → 全 PASS;提交 `feat(backend): async session-title hook via worker GenerateTitle`

## Task ST-3: 两条 turn 路径接线 + e2e(TDD)

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/api/turn.py`(一元成功路径)
- Modify: `services/backend/src/agent_cloud_backend/turn/runner.py`(流式成功路径;入参加 `spawn_title: bool`)
- Modify: `services/backend/src/agent_cloud_backend/api/turn.py` stream 端点(计算 `s.title is None` 传入)
- Test: `services/backend/tests/test_turn_e2e.py`(fake provider 脚本加一条标题响应;轮询断言 title 被填)+ 既有改名会话不被动的断言

- [ ] **失败测试**(e2e):首回合后轮询(≤5s)`session.title == "快排实现"`(FakeProvider 脚本末尾追加 `_say("快排实现")` 供 GenerateTitle 消费);第二个用例:预先 PATCH 改名的会话跑回合后 title 不变(fake 脚本相应少一条)。
- [ ] **实现**:
  - 一元(api/turn.py,`maybe_compact_after_turn` 块之后、`return TurnResponse` 之前):

```python
        if s.title is None:
            spawn_title_generation(session_id, settings=settings)
```

  - 流式:`run_turn(...)` 增 keyword 入参 `spawn_title: bool`;成功路径(`maybe_compact_after_turn` 后、`return` 前):

```python
                    if spawn_title:
                        spawn_title_generation(session_id, settings=settings)
```

    stream 端点在创建 runner 任务处传 `spawn_title=(s.title is None)`(session 行已载)。
- [ ] Run: backend 全量 + ruff → 全 PASS(既有 turn 测试的会话 title 均为 null 且无标题脚本:钩子调 worker 失败 → 吞异常留 null,断言不受影响;若有脚本耗尽报错按需补脚本或预设 title)
- [ ] 提交 `feat(backend): wire title generation into both turn success paths`

## Task ST-4: 前端首回合延迟刷新(TDD)

**Files:**
- Modify: `frontend/src/api/queryClient.ts`(导出 `refreshSessionsLater`)
- Modify: `frontend/src/components/ChatView.tsx`(onSend 捕获 wasFirst,收尾调用)
- Test: `frontend/src/api/queryClient.test.ts`(假定时器)

- [ ] **失败测试**:`refreshSessionsLater(qc, 3000)` → 立即不 invalidate,advance 3s 后 invalidate `["sessions"]` 恰一次。
- [ ] **实现** — queryClient.ts:

```ts
// 首回合结束后标题在服务端异步生成,常规 invalidate 会早于它——延迟二刷兜接。
export function refreshSessionsLater(qc: QueryClient, delayMs = 3000) {
  setTimeout(() => void qc.invalidateQueries({ queryKey: ["sessions"] }), delayMs)
}
```

ChatView `onSend`:发送前 `const wasFirst = messages.length === 0`;`await consume(...)` 后 `if (wasFirst) refreshSessionsLater(qc)`。
- [ ] Run: `cd frontend && npx vitest run && npm run lint` → 全 PASS;提交 `feat(frontend): delayed sessions refresh after first turn (async title)`

## Task ST-5: 回归 + Fable 5 对抗审查 + PR

- [ ] worker / backend(RYUK)/ ruff / 前端 + lint 全绿
- [ ] Fable 5 审查(diff 内联)重点:fire-and-forget 任务的生命周期(事件循环关闭/测试残留)、双检查竞态的真实窗口(refresh 语义)、两条 turn 路径的接线对既有重试/锁释放无副作用、e2e 轮询稳定性、worker handler 的状态码语义、BYO-key 路径
- [ ] 修复 → push → PR(`feat: auto session titles from the first question`)→ CI 绿 → 等合并指令
