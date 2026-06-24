# 流式 Subagent — 设计

## 背景与目标
让主 agent 在回合内派生**子 agent** 执行子任务:子 agent 有独立 context、复用主 agent 的工具集、共享同一 sandbox 工作区,跑完把最终输出回填给主 agent。子 agent 的思考/工具调用**实时流式透传**到前端,渲染成可折叠的"子 agent 块"。

类比 Claude Code 的 `Task` 工具,但 MVP 是**单一通用子 agent**(无 subagent_type 注册表)。

## 已批准的设计决策
- **流式透传**:子 agent 全过程实时透传到前端(非"工具黑盒")。
- **单一通用子 agent**:一种子 agent,主 agent 给 `description` + `prompt`;无类型注册表。
- **深度封顶 1**:子 agent 的工具集剥掉 `task` 自己 → 不能再派生孙 agent。
- **串行 MVP**:主 agent 一轮发多个 `task` 串行执行(沿用现有工具串行循环);并行后续。
- **共享 sandbox**:子 agent 复用主 agent 的 `SandboxToolExecutor`,看得到主 agent 的文件改动。
- **token**:子 agent 用量累加进主回合总 usage。

## 架构与数据流
事件链(现有):`worker run_turn_stream` → proto `TurnEvent` → `backend`(gRPC worker_client → SSE) → `frontend`(stream.ts → blocks.ts → 渲染)。本特性在每层加 subagent 维度。

```
主 run_turn_stream
  ├─ LLM 流 → TextDelta/ToolCallStarted/...(subagent_id="")
  └─ 执行 task 工具:
       SubagentExecutor.execute(task)
         ├─ emit SubagentStarted{id, description}
         ├─ 子 run_turn_stream(provider, inner−task, system=子模板, user=prompt)
         │    每个子事件打 subagent_id=id → 经 emit 队列穿插进主流
         └─ emit SubagentDone{id, ok};返回子 agent 最终文本为 ToolResult
```

## 核心组件(逐层)

### 1. `packages/common` — 事件
`events.py` 加两个 dataclass:`SubagentStarted(subagent_id: str, description: str)`、`SubagentDone(subagent_id: str, ok: bool)`,并入 `TurnEvent` 联合类型。现有事件(TextDelta 等)**不改字段**;subagent 归属由 proto 外层 `subagent_id` 承载(见下),worker 在透传子事件时按事件类型重建 proto 并填该字段。

### 2. `protos/agent_cloud/v1/worker.proto`
- `TurnEvent` 加 `string subagent_id = 7;`(在 oneof **外**,所有事件共享;主 agent 留空)。
- 加 `message SubagentStarted { string subagent_id = 1; string description = 2; }` 与 `message SubagentDone { string subagent_id = 1; bool ok = 2; }`,加进 `oneof event`(tag 8、9)。
- 重新生成 Python + TS 桩。

### 3. `worker` — SubagentExecutor + 嵌套 loop + emit 透传
- **`subagent.py`(新)**:`SubagentExecutor(inner: ToolExecutor, provider, emit, *, system_template, max_iterations)`。
  - `specs()` = inner.specs() + `task` 的 ToolSpec(`description`、`prompt` 两个必填 string 参数)。
  - `execute(call)`:非 `task` 委托 inner;`task` 则:
    1. 生成 `subagent_id`(worker 内单调计数器 `sub-{n}`,回合内唯一,确定性便于测试)。
    2. `await emit(SubagentStarted(id, description))`。
    3. 跑子 `run_turn_stream(provider, inner, system=渲染后的子模板, history=[], user_message=prompt, max_iterations)` —— **executor 传 inner 本身**(已不含 task,因为 SubagentExecutor 在链最外层、inner 是它包的下一层),子 agent 复用全部底层工具、共享 sandbox。
    4. 消费子事件流:给每个事件标 `subagent_id=id` 后 `await emit(event)`;遇 `TurnDone` 收集最终 assistant 文本与子 usage。
    5. `await emit(SubagentDone(id, ok=未抛错))`;返回 `ToolResult(content=子最终文本)`。子 usage 累加进 `self.accumulated_usage`(server 在主回合 TurnDone 时并入总 usage)。
- **`loop.py run_turn_stream`**:执行工具处改为"边执行边 drain emit 队列"。机制:`run_turn_stream` 持有 `emit_queue: asyncio.Queue`(传给 executor 的 `emit` 即 `queue.put`)。对每个 `call`:
  ```
  yield ToolCallStarted(...)
  exec_task = create_task(executor.execute(call))
  while True:
      get_task = create_task(emit_queue.get())
      done, _ = await wait({exec_task, get_task}, FIRST_COMPLETED)
      if get_task in done: yield get_task.result()      # 子事件
      if exec_task in done:
          get_task.cancel()
          while not emit_queue.empty(): yield queue.get_nowait()  # drain 剩余
          break
  result = exec_task.result()
  yield ToolResultEvent(...)
  ```
  对**非** subagent 工具:emit 队列恒空,`exec_task` 很快完成、drain 无事 → 行为不变(此机制对所有工具统一,无需按工具名特判)。
- **`factory.py` / `server._build_executor`**:在装饰器链**最外层**包 `SubagentExecutor`(这样它的 inner 是完整工具链、子 agent 拿得到全部工具但拿不到 task)。`task` 仅在 `subagent` 在 `enabled_tools` 时暴露(与现有 worker 原生工具一致的开关约定)。emit 队列由 `run_turn_stream` 创建并注入。
- **子 agent system 模板**(worker 常量,可调):告知模型"你是主 agent 派生的子 agent,专注完成下面这个子任务;工具与主 agent 相同(但不能再派生子 agent);完成后用简洁文本把结果/产出汇报回去,不要寒暄"。`description` 作为子任务标题注入,`prompt` 作为子 agent 的 user_message。

### 4. `backend` — 透传
`turn/worker_client.py`(proto→domain)、`turn/sse.py`(domain→SSE)、`turn/runner.py`:把 `subagent_id` 与两个新事件**机械透传**(新增分支,不改编排逻辑)。落库:子 agent 的中间消息**不**单独持久化(回合的 new_messages 仍只来自主 loop;子 agent 产出已折进 `task` 工具结果)。

### 5. `frontend` — 子 agent 块
- `api/stream.ts`:解析 `subagent_id` 与 `subagent_started`/`subagent_done`。
- `blocks.ts`:带 `subagent_id` 的事件不进顶层 block 列表,而是进对应子 agent 块的**内部 blocks**(复用现有 block 组装逻辑,递归一层)。`subagent_started` 开块(挂 description)、`subagent_done` 标记完成。
- 新组件 `SubagentCard.tsx`:可折叠(默认展开,完成后可折叠),标题显示 `description` + 运行/完成态,体内嵌渲染内部 blocks(缩进)。`MessageList`/`ChatView` 在遇到 subagent 块时渲染它。

## 关键技术:emit 透传为何用队列
`executor.execute` 是 `async def -> ToolResult`(非生成器)。把它改成 async generator 会波及**所有** executor 层与 loop,伤筋动骨——否决。emit 队列把"产生子事件"与"返回工具结果"解耦:executor 照常返回 ToolResult,中间事件经队列异步流出,`run_turn_stream` 用 `asyncio.wait(FIRST_COMPLETED)` 在"工具完成"与"队列有事件"间择一,既不轮询也不阻塞。队列对非 subagent 工具零影响。

## 取舍与边界
- **深度封顶 1**:子 agent 的 executor 就是 `SubagentExecutor` 的 inner(不含 task),故无法递归。若未来要多层,把 `SubagentExecutor` 也包进 inner 并传递 `depth`,在 `execute` 里拒超深。
- **串行**:主 loop 工具循环是串行 `await`,多个 `task` 顺序跑。并行需把循环改 `asyncio.gather` 并解决多子 agent 事件在同一主流里的交错标识(subagent_id 已能区分,但 gather 改动较大),列为后续。
- **失败**:子 `run_turn_stream` 抛错 → `SubagentDone(ok=false)` + `task` 返回 is_error 的 ToolResult(错误摘要),主 agent 自行决定下一步(与现有工具错误一致)。
- **max_iterations 用尽**:子 agent 达上限 → 取已产出的最后 assistant 文本(可能不完整)作结果 + 提示"子 agent 未自然收尾"。
- **token**:子 usage 计入主回合总 usage(context_tokens 仍取主 loop 最后一次 input_tokens,不被子 agent 干扰)。

## 分阶段
- **阶段 1(后端全链路)**:common 事件 + proto + worker(SubagentExecutor + loop drain + emit)+ backend 透传。验证:worker 单测(子 agent 跑通、事件带 subagent_id、深度封顶、失败路径、串行多 task);后端透传单测。此阶段子 agent 已能跑、事件已到前端(只是前端暂未特殊渲染,会平铺)。
- **阶段 2(前端渲染)**:stream.ts 解析 + blocks.ts 子 agent 块组装 + SubagentCard。验证:blocks 组装单测 + 组件渲染单测。

## 测试策略
- **worker**:`SubagentExecutor.execute(task)` 用 FakeProvider 脚本化子 agent 的回合(几轮工具 + 收尾),断言:透传事件序列(SubagentStarted → 子事件带 id → SubagentDone)、返回 ToolResult 为子最终文本、子 usage 累加、深度封顶(子 executor specs 不含 task)、子 agent 失败 → ok=false + is_error。`run_turn_stream` 的 drain 机制:mock 一个会 emit 几个事件的 executor,断言子事件穿插在 ToolCallStarted 与 ToolResultEvent 之间。
- **backend**:worker_client/sse 对新事件 + subagent_id 的透传单测。
- **frontend**:blocks.ts 把带 subagent_id 的事件组进子块(含嵌套工具调用);SubagentCard 折叠/展开渲染。
- 全回归三套 + 对抗审查(重点:emit 队列的取消/drain 竞态、子 agent 失败不挂主回合、深度封顶不可绕过)。

## 风险/未决
- emit 队列的 `asyncio.wait` + `get_task.cancel()` 竞态:cancel 未消费的 get_task 时若事件已入队会丢吗?—— 用 `get_nowait` drain 兜底(队列里的不丢);设计已含。实现时需测"工具完成瞬间仍有积压事件"。
- 子 agent 长跑占用主回合 max_iterations 之外的预算:子 agent 有自己的 max_iterations,但主回合总时长 = 主 + 各子 agent,需确认不触发上层(backend)的回合超时;阶段 1 验证。
