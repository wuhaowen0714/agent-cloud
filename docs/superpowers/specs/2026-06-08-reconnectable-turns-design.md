# 可重连的流式回合 + 停止 — 设计文档

> 日期:2026-06-08 · 关联:[[stateless-agent-cloud-design]] §8(回合生命周期)、§10(失败处理)、§14(后续演进:pub/sub、WS steering)

## 1. 背景与目标

**现状问题**:回合的执行跑在 SSE 连接的生命周期里。看 `api/turn.py` 的 `_sse_stream`——回合在该生成器内部消费 worker 流并吐 SSE,**助手消息只在 `TurnDone` 时落库**。客户端一断开(切会话时前端 `abort()`,或刷新),Starlette 取消该生成器 → 取消传导到 worker gRPC 流 → **回合中止**;若还没到 `TurnDone`,**消息不落库 → 整轮丢失,再也回不来**。会话锁被 shield 释放(不卡死),但产出没了。用户用正常操作(切换/刷新)就触发,体验不可接受。

**目标**:把回合执行与客户端连接**解耦**。
- 回合在服务端**独立跑到完 + 落库**,与任何连接无关。
- 客户端可**挂上 / 重挂**:POST 起回合、GET 续看;拿到**补播(已发生的事件)+ 实时尾巴**。
- 切会话、刷新都**不丢、不卡**;能**主动停止**正在跑的回合。

## 2. 范围

**做**:流式回合 `POST /turn/stream` 改为后台 runner 执行 + 进程内事件缓冲;新增 `GET /turn/stream`(重连补播+续看)、`POST /turn/cancel`(停止);前端在打开会话/刷新后自动重挂、Composer 加"停止"按钮。

**不做**:非流式 `POST /turn`(请求-响应式)保持原样;多副本下的实时重连(需 pub/sub,见 §11);回合中途细粒度 checkpoint 续跑(仍是整轮粒度,只是不再因断连而丢)。

## 3. 架构总览

```
                         ┌─────────── 后端进程 ───────────┐
POST /turn/stream ──加锁+落user消息+建请求──▶ 起 Runner 任务(asyncio.create_task)
   │ 返回订阅流                                   │ 消费 worker 流
   ▼                                              ▼ 每事件 append + notify
客户端A(发送方)◀──补播+实时── ActiveTurn{events[], cond, done, task}
                                                  │ TurnDone → 落库(DB)
GET /turn/stream ──若有进行中回合──▶ 订阅同一 ActiveTurn(补播+实时)   │ finally: 释放锁 + 从 Hub 移除
   │ 无 → 204                                     ▼
客户端B(刷新/切回)◀──补播+实时──────────  Runner 不挂在请求上 → 断连不取消它
POST /turn/cancel ──▶ active.task.cancel()
```

关键不变量:**Runner 是 `asyncio.create_task` 起的独立任务,不是请求/SSE 生成器的子任务**,所以客户端断连不会取消它;落库、锁释放都在 Runner 里完成 → 回合永不因断连而丢。

## 4. TurnHub 与 ActiveTurn(进程内注册表 + 缓冲 + 扇出)

`services/backend/src/agent_cloud_backend/turn/hub.py`:

```python
import asyncio
import uuid
from dataclasses import dataclass, field

@dataclass
class ActiveTurn:
    session_id: uuid.UUID
    events: list[dict] = field(default_factory=list)  # 已发 SSE 事件(dict),供补播
    done: bool = False
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task | None = None  # runner;起任务后回填

    async def emit(self, event: dict) -> None:
        async with self.cond:
            self.events.append(event)
            self.cond.notify_all()

    async def finish(self) -> None:
        async with self.cond:
            self.done = True
            self.cond.notify_all()


class TurnHub:
    """进程内"正在跑的回合"注册表。一会话至多一个(由会话锁保证)。"""
    def __init__(self) -> None:
        self._turns: dict[uuid.UUID, ActiveTurn] = {}

    def get(self, session_id: uuid.UUID) -> ActiveTurn | None:
        return self._turns.get(session_id)

    def register(self, active: ActiveTurn) -> None:
        self._turns[active.session_id] = active

    def remove(self, session_id: uuid.UUID) -> None:
        self._turns.pop(session_id, None)


_HUB = TurnHub()
def get_turn_hub() -> TurnHub:  # FastAPI 依赖;测试可 override
    return _HUB
```

**订阅生成器**(补播 + 实时,多订阅者各自游标,`turn/hub.py` 或 `turn/sse.py`):

```python
async def subscribe(active: ActiveTurn):
    idx = 0
    while True:
        async with active.cond:
            while idx >= len(active.events) and not active.done:
                await active.cond.wait()
            batch = active.events[idx:]
            idx = len(active.events)
            done = active.done
        for ev in batch:
            yield format_sse(ev)
        if done and idx >= len(active.events):
            return
```

新订阅者 `idx=0` → 先吐完整缓冲(补播),再等新事件,直到 `done` 且全部吐完。多个订阅者互不影响。

## 5. Runner 任务(`turn/runner.py`)

```python
async def run_turn(hub, active, *, worker_endpoint, request, session_id, heartbeat_interval):
    try:
        async with session_heartbeat(session_id, heartbeat_interval):
            async for proto_event in stream_turn_via_worker(worker_endpoint, request):
                event = turn_event_from_proto(proto_event)
                if isinstance(event, TurnDone):
                    message_ids = await _persist(session_id, event.new_messages)  # 自己开 DB session
                    await active.emit({"type": "turn_done", "usage": {...}, "message_ids": message_ids,
                                       "stop_reason": event.stop_reason})
                else:
                    await active.emit(turn_event_to_sse(event))
    except asyncio.CancelledError:
        await active.emit({"type": "error", "message": "turn cancelled", "recoverable": False})
        # 不再 re-raise:把"被取消"转成一个干净的终止事件,让 finally 正常收尾
    except grpc.aio.AioRpcError as exc:
        await active.emit(error_sse(exc.code()))
    except Exception:
        logger.exception("turn run failed")
        await active.emit({"type": "error", "message": "the turn failed", "recoverable": False})
    finally:
        await active.finish()
        await asyncio.shield(_release_session_lock(session_id))  # 复用现有实现
        hub.remove(session_id)
```

要点:
- Runner **自己开 DB session**(`get_sessionmaker()`)做落库/锁释放/心跳 —— 不依赖请求的 DB 连接(那个随请求结束而关)。
- 落库只在 Runner 里发生**一次**(旧模型里在 SSE 生成器里,断连即丢)。
- `done` 后 `hub.remove`:此后 GET 找不到 → 204 → 前端改为加载已落库消息(回合已结束,无需重放增量)。当前已挂着的订阅者持有 `active` 引用,能把缓冲吐完。
- App 关闭时取消所有在跑 Runner(lifespan,见 §9)。

## 6. 后端 API(`api/turn.py`)

`POST /sessions/{id}/turn/stream`(起):
1. 取会话、`try_acquire`(409 if busy)、落 user 消息、`build_run_turn_request` —— 都用请求 DB(同现状)。
2. `active = ActiveTurn(session_id)`;`hub.register(active)`;`active.task = asyncio.create_task(run_turn(hub, active, ...))`。
3. 返回 `StreamingResponse(subscribe(active), media_type="text/event-stream")`。
- 锁在步骤 1 加,Runner 的 finally 释放(心跳在 Runner 续租)。
- 起 Runner 失败(异常)→ rollback + release + 抛,同现状的错误分支。
- 步骤 1 的 DB 准备(加锁/落 user/建请求)用**显式 `async with get_sessionmaker()()`** 完成并在返回订阅流**之前关闭**——否则 `Depends(get_session)` 的会话会被 FastAPI 一直持有到流结束(长回合白占一个请求 DB 连接)。订阅流本身不碰 DB。

`GET /sessions/{id}/turn/stream`(续):
```python
@router.get("/stream")
async def resume(session_id, hub=Depends(get_turn_hub)):
    active = hub.get(session_id)
    if active is None:
        return Response(status_code=204)  # 没有进行中回合
    return StreamingResponse(subscribe(active), media_type="text/event-stream")
```

`POST /sessions/{id}/turn/cancel`(停止):
```python
@router.post("/cancel", status_code=204)
async def cancel(session_id, hub=Depends(get_turn_hub)):
    active = hub.get(session_id)
    if active is not None:
        active.task.cancel()  # Runner 捕获 → emit cancelled → finally 收尾
    return Response(status_code=204)  # 幂等:无在跑回合也 204
```

## 7. 前端

`api/stream.ts`:
- `streamTurn(sessionId, content, onEvent)`:不变(POST,现在拿到的是订阅流)。
- 新增 `resumeTurn(sessionId, onEvent)`:`GET /api/sessions/{id}/turn/stream`;`res.status === 204` → 返回 `null`(无在跑);否则复用 `parseSSE` + reader 逐事件回调,返回 `{ done, abort }`。
- 新增 `cancelTurn(sessionId)`:`POST /api/sessions/{id}/turn/cancel`。

`store.ts`:`LiveTurn` 加可选 `sessionId`(标记 live 属于哪个会话,便于切换时判定);其余不变。

`ChatView.tsx`:
- **发送**(onSend):同现状走 `streamTurn`(POST),喂 `live`。
- **打开会话/刷新后重挂**:在 `sessionId` 的 effect 里,若**不是刚发起 POST 的会话**,调 `resumeTurn(sid)`:
  - 返回流 → `startLive`(userText 留空——user 消息由已落库 messages 渲染)、`status:"streaming"`,把补播+实时事件按现有 handler 灌进 `live.blocks`(思考/正文/工具按序重建)。
  - 返回 `null`(204) → 无 live。
- **切走**:中断**客户端连接**(POST/GET 流的 `abort()`)+ 清掉本会话的 `live`;**不再调 cancel**(服务端回合继续)。切回时 `resumeTurn` 重挂。
- **turn_done / error**:同现状(失效 messages 查询、`clearLive`)。
- **停止按钮**:`Composer` 在 `live?.status === "streaming"` 时显示"停止"→ `cancelTurn(sid)`;Runner 会吐 `error: turn cancelled` → live 进入 error 态、刷新消息。

去重:重挂时 user 消息只来自已落库 messages(无乐观气泡,因为 `live.userText` 空);助手 live 在其下渲染。turn_done 落库后并入历史、清 live,无缝。

## 8. 数据流(四个场景)

1. **正常**:POST 起 → Runner 跑 → 客户端订阅看实时 → TurnDone 落库 → 客户端收 turn_done → 刷新 messages、清 live。
2. **切走再切回**:切走 abort 客户端连接(Runner 继续)→ 切回 `resumeTurn` GET → 补播已发事件 + 续看实时 → TurnDone 照常。
3. **刷新**:页面重载 → 打开会话时 `resumeTurn` GET → 若回合仍在跑,补播+续看;若已结束,204 → 直接看已落库结果。
4. **停止**:点"停止"→ cancel → Runner 捕获取消 → emit cancelled + 释放锁 + 移除 → 客户端收 error(cancelled)。

## 9. 并发与生命周期

- **一会话一回合**:由会话锁保证(POST busy → 409);Hub 也按 session_id 唯一。
- **清理**:Runner `done` 后 `hub.remove`;内存只被在跑回合数 × 缓冲占用。
- **App 关闭**:`main.py` lifespan 的 finally 里取消 Hub 内所有 `active.task`(避免 "task pending" 警告 + 让锁释放跑完)。
- **缓冲无界?**:单回合事件量有限(增量),回合结束即丢弃,不设硬上限;若担心超长回合,可加上限(后续)。

## 10. 失败处理

- worker 不可用 / gRPC 错 → Runner emit error 事件 + 落不了库(本来也没有新消息),锁释放、移除。客户端收 error。
- 落库失败 → emit error;锁仍释放。
- 客户端断连 → Runner 不受影响(核心目标)。
- cancel 与 worker 同时结束的竞态 → `task.cancel()` 对已完成任务是 no-op;Hub 可能已移除 → cancel 端点 `get` 返回 None → 204。

## 11. 约束(显式)

- **进程内注册表 → 实时重连只在单后端有效**。多副本下,若刷新/重连命中**另一**副本,它的 Hub 没有该回合 → GET 204 → 前端回退到"加载已落库结果"(回合仍在原副本跑到完、落库)。**所以结果永不丢(经 DB),只是跨副本时拿不到实时重连**。多副本实时重连需 pub/sub(Redis 等)广播事件 + 共享 Hub(spec §14)。
- 仍是**整轮粒度**:cancel 或 worker 崩溃丢的是当前轮的未完成产出(无半成品落库),与现有"尽力而为"一致;本设计只消除"因客户端断连而丢"。

## 12. 测试策略

- **Hub/subscribe 单元**(`tests/test_turn_hub.py`):register/get/remove;`subscribe` 对**已有缓冲**先补播、再实时、`done` 后结束;**多订阅者**各自拿到全量;晚到订阅者(done 前注册)拿到全缓冲。
- **Runner 单元**(`tests/test_turn_runner.py`,假 `stream_turn_via_worker`):事件入缓冲;TurnDone → 落库(真 Postgres 或临时)+ emit turn_done + 释放锁 + 从 Hub 移除;**不订阅也能跑完并落库**(证明与连接解耦);`task.cancel()` → emit cancelled + 收尾。
- **端点**(`tests/test_turn_stream_api.py`,假 worker 流):POST 起回合并能读到流;GET 无回合 → 204、有回合 → 补播;cancel → 204 且回合终止;**模拟断连(关闭 POST 流)后,Runner 仍落库**(轮询 messages 出现助手消息)。
- **前端**:`resumeTurn` 解析 GET SSE / 204 返回 null;`cancelTurn` 发 POST;Composer 停止按钮在 streaming 时出现并触发 cancel;ChatView resume-on-open 用补播事件重建 blocks(mock 流)。
- 原则:假 LLM/假 worker 保确定性;DB 与"解耦"行为用真实路径验证。

## 13. 后续演进

- pub/sub(Redis Streams / NATS)替换进程内 Hub → 多副本实时重连 + 水平扩展(spec §14 第②跳)。
- WebSocket 双向 → 回合进行中实时 steering(spec §14 第①跳)。
- 回合事件持久化(落 DB/对象存储)→ 跨进程重启也能补播 + 审计。
- 细粒度 checkpoint 续跑(工具幂等)。
