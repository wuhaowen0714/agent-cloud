# 会话摘要压缩(Session Compaction)— 设计文档

> 日期:2026-06-08 · 关联:[[stateless-agent-cloud-design]] §1(非目标:compaction)、§14(后续:更完善 compaction)、line 163

## 1. 背景与目标

`assemble.py` 每回合把**整段历史**原样发给 LLM,没有任何摘要/截断。长会话 prompt 无限增长,迟早超模型上下文上限 → 回合报 `context_length_exceeded`(400),且历史只增不减 → **该会话彻底卡死**(每次重试都太大)。spec 早已要求 compaction(line 163),但未实现。

**目标**:长会话**不死**,且尽量**保住早期要点**(目标/决定/产出/未完成事项)。

## 2. 范围

**做**:
- 主动压缩(primary):**回合后**用模型返回的**真实 token 数**判阈值,超了就把早期历史摘要进 session,下一轮变小。
- 被动兜底(safety net):回合撞 `context_length_exceeded` 400 → **强制压缩** + 返回**可重试**错误(用户重试即恢复)。
- 摘要由 worker 做(LLM key 只在 worker),增量(prior_summary + 新折叠 → 新摘要)。

**不做(v1)**:撞 400 后的**透明自动重试**(v1 是"压缩 + 可重试错误",手动重一次;自动重试留后续)、精确按模型 window 自适应阈值(window 不可靠获取,用配置 token 数)、轮内(单回合多步)压缩、分支树。

## 3. 架构总览

```
回合 N 跑完 → TurnDone 带 context_tokens(=最后一次 LLM 调用的 input_tokens,模型数的真实上下文大小)
            → 后端 post-turn:context_tokens > 阈值 ? → worker.Summarize(增量) → 写 session.summary/summary_through_seq
                                                          (在响应返回之后做,用户无感)
下一回合 → assemble:history = seq > summary_through_seq 的消息;history_summary = session.summary
        → worker 把 history_summary 拼进 system(# 此前对话摘要)
        ── 若仍撞 400 context_length_exceeded ── worker 报 RESOURCE_EXHAUSTED → 后端 force_compact + 可重试错误
```

关键:**触发信号是模型返回的真实 token 数,不是字符估算**;**主动在回合后**(零额外延迟);**被动兜底**保证永不死。

## 4. proto 变更(`protos/agent_cloud/v1/worker.proto`)

```proto
service Worker {
  rpc RunTurn(RunTurnRequest) returns (RunTurnResponse);
  rpc RunTurnStream(RunTurnRequest) returns (stream TurnEvent);
  rpc Summarize(SummarizeRequest) returns (SummarizeResponse);   // 新增
}

message RunTurnRequest {
  // …现有 1–10…
  string history_summary = 11;   // 新增:此前历史的摘要,worker 拼进 system
}

message RunTurnResponse {
  // …1–4…
  int64 context_tokens = 5;      // 新增:最后一次 LLM 调用的 input_tokens(真实上下文大小)
}
message TurnDone {
  // …1–4…
  int64 context_tokens = 5;      // 新增:同上
}

message SummarizeRequest {       // 新增
  Agent agent = 1;
  string prior_summary = 2;
  repeated Msg messages = 3;     // 要折叠进摘要的历史
}
message SummarizeResponse {      // 新增
  string summary = 1;
  int64 input_tokens = 2;
  int64 output_tokens = 3;
}
```
`bash scripts/gen_protos.sh` 重生成 `worker_pb2`/`worker_pb2_grpc`。

## 5. common / codec 变更(`packages/common`)

- `TurnDone` dataclass 加 `context_tokens: int = 0`;`RunTurnResponse` 映射加 `context_tokens`。
- codec `turn_event_to_proto`/`from_proto`、`run_turn_response` 映射带上 `context_tokens`。
- 新增 `SummarizeRequest`/`SummarizeResponse` 的 common 类型 + codec(或 worker_client 直接用 proto,backend 侧用 codec 转 Msg)。

## 6. worker 变更

- **loop.py**:循环里除现有 `usage += `,额外记 `last_input = completed.usage.input_tokens`(每次覆盖);`TurnResult`/`TurnDone` 带 `context_tokens = last_input`(最后一次调用的输入大小)。
- **context.py `_build_context_and_history`**:若 `request.history_summary` 非空,作为一段 `# 此前对话摘要\n{summary}` 拼进 **system**(放在基础 prompt 之后、文档之前)。
- **server.py `Summarize` handler**:
  - `provider = provider_factory(agent.model, agent.provider, agent.key_ref)`。
  - system = 压缩提示("你是对话压缩器,把对话浓缩成要点:目标、关键事实/决定、产出的文件、未完成事项;保留后续对话需要的信息;不要寒暄/客套")。
  - 把 `messages`(折叠的历史)作为 history,`user_message = "请将以上对话压缩成简明要点。已有摘要(合并更新):\n{prior_summary}"`,做**一次** provider 非流式 completion(不走工具 loop)。
  - 返回 `SummarizeResponse(summary=text, input_tokens, output_tokens)`。
- **openai_provider.py 上下文超限识别**:completion 调用包 try,捕获 `openai.BadRequestError`(400)且报文/`code` 命中上下文超限(`context_length_exceeded` 或含 "context"/"maximum"/"length"/"token" 等)→ 抛自定义 `ContextWindowExceeded`。
- **server.py RunTurn/RunTurnStream**:捕获 `ContextWindowExceeded` → `context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "context window exceeded")`(区别于普通 INTERNAL),供 backend 识别走兜底。

## 7. backend:session 字段 + 迁移

`models/session.py` 加:
```python
summary: Mapped[str] = mapped_column(default="", nullable=False)
summary_through_seq: Mapped[int] = mapped_column(default=-1, nullable=False)  # ≤ 此 seq 的消息已并入 summary
```
alembic 迁移加这两列(默认 ""/-1)。

## 8. backend:compaction 模块(`turn/compaction.py`)

- `summarize_via_worker(endpoint, agent, prior_summary, messages) -> str`:调 worker `Summarize` RPC。
- `_fold_boundary(history_after, keep_recent) -> (fold_msgs, boundary_seq) | None`:`history_after` = seq > summary_through_seq 的消息;保留最后 `keep_recent` 条,其余为 `fold_msgs`;不足以折叠(≤ keep_recent)返回 None。
- `async def compact(session_id, *, worker_endpoint, keep_recent)`:开独立 DB session 读 session + history → `_fold_boundary` → 若可折叠:`summarize_via_worker(prior_summary=session.summary, fold_msgs)` → 写 `session.summary = new`、`summary_through_seq = boundary_seq` → commit。返回是否压了。
- `async def maybe_compact_after_turn(session_id, context_tokens, *, settings)`:`context_tokens > settings.compaction_token_threshold` 才调 `compact(...)`。**回合后调用**(用真实 token 数)。
- `async def force_compact(session_id, *, settings)`:被动兜底——用更小的 `keep_recent`(如 2)`compact`,尽量把上下文压下去。

**所有主动压缩调用 best-effort**:`maybe_compact_after_turn` 内部 try/except 吞掉异常(log 即可)——回合**已经成功**,绝不能因为"事后压缩"失败(worker 超时/摘要出错)而把这轮搞坏或卡住锁。被动 `force_compact` 失败则继续走"可重试"错误。

## 9. backend:assemble 变更

`build_run_turn_request`:
```python
history = await MessageRepository(db).list_by_session(session.id)
history = [m for m in history if m.id != exclude_message_id and m.seq > session.summary_through_seq]
history = _strip_unanswered_user_messages(history)
# …RunTurnRequest(… history_summary=session.summary, …)
```
即:只发摘要点之后的消息 + 把 `session.summary` 作为 `history_summary` 传给 worker。

## 10. backend:turn 端点接线

- **post-turn 主动**(两端点):
  - 流式(runner):`TurnDone` 落库 + emit turn_done **之后**(响应已到客户端),调 `maybe_compact_after_turn(session_id, ev.context_tokens, settings=...)`,再 `finish`。压缩延迟对用户隐藏。
  - 非流式(`run_turn_endpoint`):落库后调 `maybe_compact_after_turn(..., response.context_tokens, ...)`。
- **被动兜底**(两端点):worker 调用/流抛 `AioRpcError` 且 `code()==RESOURCE_EXHAUSTED` →
  - `await force_compact(session_id, settings=...)`;
  - emit/return **可重试**错误(`{"type":"error","message":"上下文超限,已自动压缩,请重试","recoverable":true}`)。
  - 用户点重试(现有"可重试"UI)→ 下一轮用压缩后的上下文 → 成功。(透明自动重试留后续。)
- `_RECOVERABLE` 集合加 `RESOURCE_EXHAUSTED`(其错误展示为可重试)。

## 11. 配置(`config.py`)

```python
compaction_token_threshold: int = 32000   # context_tokens 超此值 → 回合后压缩(设成模型 window 的 ~70–80%)
compaction_keep_recent: int = 8           # 压缩时保留逐字的最近消息条数
```
说明:阈值是**真实 token 数**(模型返回的),不是字符;手动配(无法可靠自动获知任意模型 window),但被动兜底保证设歪也不死。

## 12. 数据流

1. **正常**:回合跑 → context_tokens 未超阈值 → 不压,零开销。
2. **触发主动**:某轮 context_tokens > 阈值 → 响应返回后,后台把早期历史(留最近 8 条)摘要进 session → 下一轮只发 摘要 + 近 8 条 + 新消息 → context_tokens 回落。
3. **撞 400(兜底)**:阈值设歪/单轮暴涨导致 worker 报 RESOURCE_EXHAUSTED → 后端 force_compact(留最近 2 条)+ 可重试错误 → 用户重试 → 成功。
4. 摘要**增量**:每次 `Summarize(prior_summary + 新折叠)`,提示词压住长度。

## 13. 测试

- **worker**:`Summarize` handler(假 provider → 返回摘要 + usage);loop 报 `context_tokens` = 最后一次调用 input_tokens(多步时 ≠ 累加和);`ContextWindowExceeded` 识别 + 映射 RESOURCE_EXHAUSTED;`history_summary` 进 system。
- **backend**:`_fold_boundary`(纯函数:留 keep_recent、不足返 None)单测;`compact`(假 worker Summarize + 真 DB → 写 summary/summary_through_seq);`maybe_compact_after_turn`(超阈值才压);`assemble`(summary_through_seq 过滤 + history_summary 注入);端点 post-turn 调用 + RESOURCE_EXHAUSTED→force_compact+可重试。
- **迁移**:两列存在、默认值。
- **实景**:把阈值调很小,跑几轮长对话 → 看 session.summary 被填、后续回合历史变短、对话仍连贯;构造超限 → 可重试恢复。

## 14. 后续演进

- 撞 400 的**透明自动重试**(runner 内 force_compact + 重新 assemble + 重订阅,首个 LLM 调用前失败时无缝)。
- 按模型 window 自适应阈值(维护 model→window 表 / 探测)。
- 轮内(单回合多步累积)压缩;精确 tokenizer 预估(主动层也能 pre-turn 预判)。
- 摘要分层(摘要的摘要),应对超长会话摘要本身膨胀。
