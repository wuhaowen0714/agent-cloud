# 回合失败的透明自动恢复(Turn Recovery / Auto-Retry)设计

> 日期:2026-06-08 · 关联:[[2026-06-08-session-compaction-design]](压缩 + force_compact + RESOURCE_EXHAUSTED)、可重连流式回合(turn/hub.py、runner.py)、[[project_frontend]]

## 目标

让回合失败对用户尽量无感:撞到**可恢复**失败时后端在同一回合内自动恢复并重试,用户不需要手动重发。两类可恢复失败:

1. **上下文超窗**(worker → gRPC `RESOURCE_EXHAUSTED`):自动 `force_compact` 后重发同一回合。
2. **瞬时基础设施错误**(后端↔worker 这一跳的 `UNAVAILABLE` / `DEADLINE_EXCEEDED` / `INTERNAL`):指数退避后重试同一请求。

只有**重试耗尽**或**不可恢复**(压缩已无进展、仅剩最近一条仍超窗)时,才向用户暴露最终错误,并据 `recoverable` 给出正确的措辞与手动重试入口。

## 背景与现状(为何要做)

- 压缩(Plan 12)已让后端在超窗时 `force_compact` 并返回 `RESOURCE_EXHAUSTED`(流式)/ 503·413(非流式),但**前端没用上 `recoverable`**:`MessageList.tsx` 写死显示"⚠ …,可重试。",不区分可恢复/不可恢复,也没有真正的重试动作。后端做了一半,价值没兑现。
- 后端撞 `RESOURCE_EXHAUSTED` 现在是"压缩完就把错误抛给用户",而压缩后的重试几乎必然成功——本可对用户透明。
- 瞬时的后端↔worker 失败现在直接变成一次失败的回合,无自动重试。

## 非目标(本设计不做)

- 跨"整回合已落库"的重放/续跑:本设计只在**单个回合内**重试;流式下助手消息仅在 `TurnDone` 成功时落库,中途失败 DB 无半成品,故无需回滚已落库内容。
- 针对单个工具调用的细粒度重试。
- 重试遥测/可视化面板。
- worker↔LLM 那一跳的重试(openai SDK 已自带 `max_retries` 退避 429/5xx;本设计覆盖的是后端↔worker 跳,二者互补)。

## 架构总览

每条路径各自持有一个重试循环,共享一个**纯策略模块** `turn/retry.py`,把"怎么判失败、退避多久、上限多少"与"怎么发事件/怎么落库"解耦:

- **`turn/retry.py`(纯逻辑、易单测)**:
  - `RetryAction` 枚举:`COMPACT_RETRY`(超窗,先压缩再重试)、`BACKOFF_RETRY`(瞬时,退避后重试)、`GIVE_UP`(放弃)。
  - `classify(code: grpc.StatusCode) -> "overflow" | "transient" | "fatal"`:`RESOURCE_EXHAUSTED`→overflow;`{UNAVAILABLE, DEADLINE_EXCEEDED, INTERNAL}`→transient;其余→fatal。
  - `RetryPolicy`(由 `Settings` 构造):`max_overflow_retries`、`max_transient_retries`、`max_total_attempts`、`backoff_seconds(attempt_index) -> float`(指数:`base * 2**i`,带上限)。
  - `decide(code, *, overflow_used, transient_used, total_used, compaction_progressed) -> RetryAction`:综合各计数 + 压缩是否有进展,返回动作。压缩无进展(`compaction_progressed is False`)即便未到 overflow 上限也 `GIVE_UP`。
- **流式 runner**:外层套重试循环,重试前发 `reset` 事件并清补播缓冲,然后用(可能重新组装的)请求重开 worker 流。
- **非流式 endpoint**:同一策略,循环到成功/放弃;无流式与局部输出问题。

> 备选 B(抽一个对流式/一元都自洽的统一 turn-executor)改动更大、抽象更绕;备选 C(只处理"未流出"简单情形)达不到"reset 全透明"。均不采用。

## 重试策略细节

| 失败类 | 触发 | 动作 | 默认上限 | 耗尽后 `recoverable` |
|---|---|---|---|---|
| overflow | `RESOURCE_EXHAUSTED` | `force_compact` → 有进展则**重新组装**(拿新摘要+过滤历史)并重试;无进展立即放弃 | 2 | `false`("上下文过大,请开新会话") |
| transient | `UNAVAILABLE`/`DEADLINE_EXCEEDED`/`INTERNAL` | 退避 `base·2^i` 秒后重试同一请求 | 3 | `true`(用户可稍后手动重试) |
| fatal | 其它 code(如 `INVALID_ARGUMENT`/`FAILED_PRECONDITION`) | 不重试 | — | 按 `_RECOVERABLE` 集合判定(现状) |

- 另设 `max_total_attempts`(默认 6 = 1 次首发 + overflow/transient 重试上限之和)做**纯兜底**,防两类交替的病态组合无限循环;正常永远先撞到各自的分类上限。
- `force_compact` 已返回是否有进展(Plan 12b);overflow 重试直接复用它做进展门控。
- **关于 `INTERNAL`**:worker 把"重试耗尽的瞬时上游 5xx"和"确定性失败(provider 报错 / loop 守卫)"都收敛成 `INTERNAL`(catch-all)。把它纳入自动重试意味着确定性失败时会白跑至多 `max_transient_retries` 次才报错——代价被上限+退避**有界**,且可配。若实测确定性失败偏多,可把 `INTERNAL` 从瞬时类移出(改为"显式提示+手动重试"),只留 `UNAVAILABLE`/`DEADLINE_EXCEEDED` 自动重试。

## 流式路径(runner,前端走这条)

1. **重新组装请求改为 thunk**:`stream_turn_endpoint` 仍先组装一次 `request`(保留 fail-fast:组装失败→释放锁→抛错,不返回 200 流),并额外构造一个 `reassemble: Callable[[], Awaitable[RunTurnRequest]]` 闭包传给 runner。闭包内部开**新** DB session、加载会话、调 `build_run_turn_request`(因此能读到刚 `force_compact` 写回的新 summary/边界)。`run_turn` 新增参数 `reassemble`。
2. **重试循环**:首次尝试用传入的 `request`;每次重试调 `reassemble()` 取新请求(transient 时历史未变、结果≈同一请求,无害;overflow 时拿到压缩后的请求)。
3. **reset 事件**:重试前向 `active` 发 `{"type": "reset"}`,前端清掉本回合已显示的块;**同时清空 `ActiveTurn` 的补播缓冲**(`ActiveTurn.reset()`:通知在线订阅者后清空 events 列表,使随后重连的客户端只补播重试后的事件)。
4. **无半成品**:助手/工具消息只在 `TurnDone` 成功时经 `_persist` 落库;中途失败 DB 只剩那条 user 消息——重试无需清 DB,reset 只清前端显示。
5. **取消**:退避用可取消的 `asyncio.sleep`;重试循环每轮入口检查取消;`CancelledError` 仍走现有"turn cancelled"干净收尾 + `finally` 释放锁。
6. **压缩仍在心跳上下文内**:重试循环整体在 `session_heartbeat` 内,续租不断(沿用 Plan 12b 的修法)。
7. **最终失败**:重试耗尽/fatal → 发 `error_sse(code)` 或不可恢复 error(overflow 无进展),走现有 `finally`。

## 非流式路径(endpoint)

`run_turn_endpoint` 把"调 worker → 落库 → 主动压缩"包进同一重试循环:

- overflow:`force_compact` 有进展 → `await db.refresh(s)`(让 DI session 读到新 summary)→ 用 `build_run_turn_request` 重新组装 → 重试;无进展 → 413。
- transient:退避后重试同一请求;耗尽 → 503。
- 成功:落库 + 回合后主动压缩(现状)+ 正常返回。
- 全程持锁(`finally` 释放),与现状一致。

## reset 事件 + 前端

- **新 SSE 事件** `{"type": "reset"}`:加入 `turn/sse.py` 的事件映射与前端 `types.ts` 的事件联合。
- **前端处理**:
  1. `ChatView` 收到 `reset` → 清空 live 回合的块、保留 `status: "streaming"`(在 `store.ts` 加 `resetLive()`)。自动重试期间用户至多看到一次清屏闪烁。
  2. **真正读 `recoverable`**(删掉 `MessageList.tsx` 写死的"可重试"):
     - `recoverable: true`(瞬时耗尽)→ "服务暂时不可用,请稍后重试" + **重试按钮**(重发上一条 user 消息)。
     - `recoverable: false`(超窗无进展)→ "上下文过大,请开新会话",不提供重试。
  3. 手动重试 = 取该会话最后一条 user 消息文本,重新发起一次回合(无需新端点)。

## 配置(Settings,可调,给默认)

```
turn_max_overflow_retries: int = 2
turn_max_transient_retries: int = 3
turn_max_total_attempts: int = 6          # 1 首发 + 两类重试上限之和;纯兜底
turn_retry_backoff_base_seconds: float = 0.5   # 第 i 次重试等 base * 2**i 秒,单步封顶 8s
```

## 错误语义与边界

- overflow 首 call(入口超窗,最常见)→ 还没流出任何东西 → 重试天然干净,reset 也无害(无块可清)。
- overflow/transient 中途(已流出局部)→ reset 清块后重来。
- 压缩无进展 → 不可恢复(413 / `recoverable:false`),终止无效重试。
- 重试期间会话锁始终持有,并发同会话回合仍 409。
- 重连补播:reset 后缓冲已清,重连客户端只看到重试后的流。

## 测试

- **`turn/retry.py` 纯单测**:`classify` 三分类;`backoff_seconds` 序列与封顶;`decide` 在各计数/进展组合下的动作(含无进展→GIVE_UP、到上限→GIVE_UP、total 兜底)。
- **runner(testcontainer + fake worker stream)**:
  - 超窗→压缩→reset→重试成功(`summarize_via_worker` 打桩;断言出现 reset 事件、最终 turn_done、summary 落库)。
  - 瞬时→退避→重试成功(fake 先抛 `UNAVAILABLE` 再正常;退避用极小 base 或打桩 sleep)。
  - 重试耗尽→最终 error 且 `recoverable` 正确(瞬时 true / 超窗无进展 false)。
  - reset 清补播缓冲:重试后用 GET 重连只补播重试后的事件。
  - 重试/退避期间取消 → 干净收尾、锁释放。
- **endpoint(非流式)**:超窗自动重试后 200 / 无进展 413 / 瞬时耗尽 503。
- **前端**:reset 清块;`recoverable` 文案分支;手动重试重发上一条 user 消息。

## 涉及文件

- 新增:`services/backend/src/agent_cloud_backend/turn/retry.py` + `tests/test_retry.py`。
- 改:`turn/runner.py`(重试循环 + reassemble + reset)、`api/turn.py`(非流式重试循环 + 流式传 reassemble)、`turn/hub.py`(`ActiveTurn.reset()`)、`turn/sse.py`(reset 事件映射)、`config.py`(4 个参数)。
- 前端:`types.ts`(reset 事件)、`store.ts`(`resetLive`)、`components/ChatView.tsx`(处理 reset + 最终 error 读 recoverable)、`components/MessageList.tsx`(分支文案 + 重试按钮)。
- 测试:`tests/test_turn_runner.py`、`tests/test_turn_stream_endpoint.py`、`tests/test_turn_endpoint.py`、前端组件测试。
