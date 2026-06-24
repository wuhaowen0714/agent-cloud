# 流式 Subagent — 阶段 1 实现计划(后端全链路)

> **执行方式:** controller 直接 TDD 实现(本环境子 agent 大批量写入会截断),子 agent 留对抗审查。每个 Task 一组提交。Steps 用 `- [ ]` 跟踪。

**Goal:** 主 agent 能调 `task` 工具派生**流式**子 agent;子 agent 复用全部工具(除 task)、共享 sandbox,事件带 `subagent_id` 透传到前端(阶段 1 前端暂平铺,阶段 2 渲染成块)。

**Architecture:** `SubagentExecutor`(装饰器链最外层)暴露 `task` 工具,handler 跑嵌套 `run_turn_stream`;子事件经 **emit 队列**穿插进主 `run_turn_stream`。proto `TurnEvent` 加外层 `subagent_id` + `SubagentStarted`/`SubagentDone` 事件。

**Tech Stack:** Python async(worker/backend)、grpc/protobuf、pytest(asyncio_mode=auto)。spec: `docs/superpowers/specs/2026-06-24-streaming-subagent-design.md`。

---

## File Structure(阶段 1)
| 文件 | 职责 | 改动 |
|---|---|---|
| `packages/common/src/agent_cloud_common/events.py` | domain 事件 | +`SubagentStarted`/`SubagentDone` dataclass,并入 `TurnEvent` 联合 + `subagent_id` 字段策略 |
| `protos/agent_cloud/v1/worker.proto` | 线格式 | `TurnEvent` 加 `subagent_id` + 两个 message,加进 oneof |
| `packages/common/src/agent_cloud_common/codec.py` | event↔proto | `turn_event_to_proto` + 反向加分支、透传 `subagent_id` |
| `services/worker/src/agent_cloud_worker/subagent.py` | **新** | `SubagentExecutor` + `task` ToolSpec + 子 agent system 模板 |
| `services/worker/src/agent_cloud_worker/loop.py` | agent loop | `run_turn_stream` 加 `emit` 参数 + 工具执行 drain 子事件 |
| `services/worker/src/agent_cloud_worker/server.py` | 接线 | `_build_executor` 最外层包 `SubagentExecutor`;`RunTurnStream` 建 emit 队列注入 |
| `services/backend/src/agent_cloud_backend/turn/sse.py` | proto→SSE | 加 `subagent_id` + 两个新事件的透传分支 |

事件归属策略:domain 事件**不**逐个加 `subagent_id` 字段(避免改 6 个 dataclass);改为 `run_turn_stream`/`SubagentExecutor` 在透传子事件时用 `(event, subagent_id)` 元组传递,`turn_event_to_proto(event, subagent_id="")` 把 id 填进 proto 外层。`SubagentStarted/Done` 自带 id 字段。

---

## Task 1: domain 事件 + codec 往返

**Files:** Modify `packages/common/src/agent_cloud_common/events.py`、`codec.py`;Test `packages/common/tests/test_codec.py`(若无则建)。

- [ ] **Step 1: 失败测试** — `events.py` 加 `@dataclass class SubagentStarted: subagent_id: str; description: str` 与 `class SubagentDone: subagent_id: str; ok: bool`,加进 `TurnEvent = Union[...]`。`codec.turn_event_to_proto(event, subagent_id="")` 签名加第二参数。测试:
```python
def test_subagent_started_roundtrips():
    ev = SubagentStarted(subagent_id="sub-1", description="算个数")
    p = turn_event_to_proto(ev)
    assert p.subagent_started.subagent_id == "sub-1" and p.subagent_started.description == "算个数"
def test_text_delta_carries_subagent_id():
    p = turn_event_to_proto(TextDelta(text="hi"), subagent_id="sub-1")
    assert p.subagent_id == "sub-1" and p.text_delta.text == "hi"
def test_default_subagent_id_empty():
    assert turn_event_to_proto(TextDelta(text="hi")).subagent_id == ""
```
- [ ] **Step 2: 跑测试看 fail**(proto 还没字段 → AttributeError;先做 Task 2 的 proto 再回来,或本 Task 与 Task 2 合并提交)。
- [ ] **Step 3: 实现** — 见 Task 2(proto)后,`turn_event_to_proto` 加 `subagent_id` 形参填到 `p.subagent_id`,加 `SubagentStarted/Done` 两个 isinstance 分支。
- [ ] **Step 4: 跑测试 PASS**。
- [ ] **Step 5: commit** `feat(common): subagent 事件 + codec subagent_id 透传`。

## Task 2: proto + 重新生成桩

**Files:** Modify `protos/agent_cloud/v1/worker.proto`;运行 `scripts/gen_protos.sh`。

- [ ] **Step 1: 改 proto** — `TurnEvent` 加 `string subagent_id = 7;`(oneof 外);新增:
```proto
message SubagentStarted { string subagent_id = 1; string description = 2; }
message SubagentDone { string subagent_id = 1; bool ok = 2; }
```
加进 `oneof event { ... SubagentStarted subagent_started = 8; SubagentDone subagent_done = 9; }`。
- [ ] **Step 2: 重新生成** — `bash scripts/gen_protos.sh`;确认 `worker_pb2.py`/`.pyi` + TS 桩更新(diff 看 `subagent_id`/`SubagentStarted`)。
- [ ] **Step 3: commit** `feat(proto): TurnEvent subagent_id + SubagentStarted/Done`(与 Task 1 一起跑 common 测试 PASS 后提交)。

## Task 3: run_turn_stream emit 注入 + drain 子事件

**Files:** Modify `loop.py`(`run_turn_stream`);Test `services/worker/tests/test_loop_subagent_stream.py`(新)。

- [ ] **Step 1: 失败测试** — `run_turn_stream` 加 kwarg `emit: asyncio.Queue | None = None`。提供一个 mock executor,其 `execute` 在返回 ToolResult 前往 `emit` 放两个 `(TextDelta("子a"), "sub-1")` 元组。断言主流事件顺序:`ToolCallStarted` → 两个带 `subagent_id="sub-1"` 的子事件 → `ToolResultEvent`。
```python
async def test_stream_interleaves_subagent_events():
    q = asyncio.Queue()
    class EmitExec:
        def specs(self): return [ToolSpec(name="task", description="d", input_schema={})]
        async def execute(self, call):
            await q.put((TextDelta(text="子a"), "sub-1"))
            await q.put((TextDelta(text="子b"), "sub-1"))
            return ToolResult(call_id=call.id, content="done", is_error=False)
    # provider 脚本:一轮 task 调用 → 一轮收尾
    events = [e async for e in run_turn_stream(prov, EmitExec(), system="s", history=[], user_message="go", emit=q)]
    # 断言子事件夹在 ToolCallStarted 与 ToolResultEvent 之间、且带 subagent_id
```
- [ ] **Step 2: 跑 fail**(emit 参数不存在)。
- [ ] **Step 3: 实现 drain** — 工具执行循环(loop.py:191-201)改:
```python
exec_task = asyncio.create_task(executor.execute(call))
if emit is not None:
    while True:
        get_task = asyncio.create_task(emit.get())
        done, _ = await asyncio.wait({exec_task, get_task}, return_when=asyncio.FIRST_COMPLETED)
        if get_task in done:
            sub_ev, sub_id = get_task.result()
            yield _tagged(sub_ev, sub_id)   # 子事件,带 subagent_id
        if exec_task in done:
            get_task.cancel()
            while not emit.empty():
                sub_ev, sub_id = emit.get_nowait()
                yield _tagged(sub_ev, sub_id)
            break
    result = exec_task.result()
else:
    result = await exec_task
```
`run_turn_stream` 主流的 yield 现在产出 `(event, subagent_id)` 元组(主 agent 事件 id=""),由 server 转 proto;或保持 yield 裸事件、子事件用包装类型。**决定:统一 yield `TurnEvent`,子事件归属由 server 侧 turn_event_to_proto 调用点的 subagent_id 决定**——为此 `run_turn_stream` yield `tuple[TurnEvent, str]`(事件, subagent_id)。改主流所有 `yield X` 为 `yield (X, "")`。`_tagged` 即 `(sub_ev, sub_id)`。
- [ ] **Step 4: 跑 PASS**。
- [ ] **Step 5: commit** `feat(worker): run_turn_stream emit 队列透传子事件`。

## Task 4: SubagentExecutor + task 工具

**Files:** Create `services/worker/src/agent_cloud_worker/subagent.py`;Test `services/worker/tests/test_subagent.py`(新)。

- [ ] **Step 1: 失败测试** — 用 `FakeProvider`(provider.py 已有)脚本化子 agent:一轮发 `read_file` 工具调用、一轮收尾文本 "子结果"。`SubagentExecutor(inner=FakeInnerExec, provider=FakeProvider([...]), emit=q, max_iterations=5)`。调 `execute(ToolCall(name="task", arguments={"description":"读文件","prompt":"读 a.txt"}))`。断言:
  - 返回 `ToolResult(content 含 "子结果", is_error=False)`;
  - `q` 里依次有 `SubagentStarted(id, "读文件")` → 子 agent 的事件元组(带同一 id)→ `SubagentDone(id, ok=True)`;
  - `executor.specs()` 含 `task`;子 run_turn_stream 用的 executor(inner)的 specs **不含** task(深度封顶);
  - 非 task 调用委托 inner;
  - 子 agent 抛错 → `SubagentDone(ok=False)` + 返回 `is_error=True` 的 ToolResult。
- [ ] **Step 2: 跑 fail**。
- [ ] **Step 3: 实现** — `SubagentExecutor`:
```python
class SubagentExecutor:
    def __init__(self, inner, provider, emit, *, max_iterations=10):
        self._inner, self._provider, self._emit = inner, provider, emit
        self._max_iter = max_iterations
        self._n = 0
        self.accumulated_usage = Usage()
    def specs(self):
        return [*self._inner.specs(), _TASK_SPEC]
    async def execute(self, call):
        if call.name != "task":
            return await self._inner.execute(call)
        self._n += 1; sid = f"sub-{self._n}"
        desc = call.arguments.get("description", ""); prompt = call.arguments.get("prompt", "")
        await self._emit.put((SubagentStarted(subagent_id=sid, description=desc), ""))
        final, ok = "", True
        try:
            async for sub_ev, _ in run_turn_stream(
                self._provider, self._inner, system=_SUBAGENT_SYSTEM.format(description=desc),
                history=[], user_message=prompt, max_iterations=self._max_iter, emit=None):
                if isinstance(sub_ev, TurnDone):
                    final = _last_assistant_text(sub_ev.new_messages)
                    self.accumulated_usage = _add(self.accumulated_usage, sub_ev.usage)
                else:
                    await self._emit.put((sub_ev, sid))
        except Exception as exc:
            ok = False; final = f"subagent failed: {exc}"
        await self._emit.put((SubagentDone(subagent_id=sid, ok=ok), ""))
        return ToolResult(call_id=call.id, content=final or "(subagent produced no output)", is_error=not ok)
```
注意:子 run_turn_stream 自身 `emit=None`(它的工具不再透传二级;子 agent 的事件由本 execute 手动转发,统一打 sid)。`_TASK_SPEC`=ToolSpec(name="task", description="Delegate a subtask to a fresh sub-agent with the same tools; returns its final summary.", input_schema={description, prompt 必填})。`_SUBAGENT_SYSTEM`=spec 里的通用模板。
- [ ] **Step 4: 跑 PASS**。
- [ ] **Step 5: commit** `feat(worker): SubagentExecutor + task 工具`。

## Task 5: 接线(server/_build_executor + emit 队列)

**Files:** Modify `server.py`(`_build_executor`、`RunTurnStream`);Test `services/worker/tests/test_subagent_wiring.py`(新)。

- [ ] **Step 1: 失败测试** — `_build_executor` 返回的 executor:`subagent` 在 enabled_tools 时 specs 含 task、否则不含;最外层是 SubagentExecutor(其 inner 是完整链)。`RunTurnStream` 给 `run_turn_stream` 传了非 None 的 emit 队列、且把 emit 传进了 SubagentExecutor(同一个队列实例)。这是 memory 记的"配 key/wiring 漏传"高发区,必加 wiring 测试。
- [ ] **Step 2: 跑 fail**。
- [ ] **Step 3: 实现** — `_build_executor` 在 `return executor, sandbox_exec` 前包:
```python
emit_queue = asyncio.Queue()
if subagent_enabled(enabled_tools):
    executor = SubagentExecutor(executor, provider=<本回合 provider>, emit=emit_queue, max_iterations=self._settings.max_iterations)
```
provider 在 RunTurnStream 里由 factory 造,需把 provider 传进 `_build_executor`(改签名)或在 RunTurnStream 组装。`RunTurnStream` 调 `run_turn_stream(..., emit=emit_queue)`(同一队列)。加 `subagent_enabled` 到 tools 的开关函数族。
- [ ] **Step 4: 跑 PASS**。
- [ ] **Step 5: commit** `feat(worker): 接线 SubagentExecutor + emit 队列`。

## Task 6: backend 透传(proto→SSE)

**Files:** Modify `services/backend/src/agent_cloud_backend/turn/sse.py`(+ 必要时 `runner.py`);Test `services/backend/tests/test_subagent_sse.py`(新)。

- [ ] **Step 1: 失败测试** — 构造 proto `TurnEvent`(text_delta + subagent_id="sub-1";subagent_started;subagent_done),过 sse 转换,断言 SSE payload 含 `subagent_id` 字段、且 `subagent_started`/`subagent_done` 映射成对应 SSE 事件类型。
- [ ] **Step 2: 跑 fail**。
- [ ] **Step 3: 实现** — sse.py 的 proto→SSE 映射加:每个事件的 SSE dict 带 `subagent_id`(从 `event.subagent_id`,空则省略);`subagent_started`→`{type:"subagent_started", id, description}`、`subagent_done`→`{type:"subagent_done", id, ok}`。机械透传,不改编排。
- [ ] **Step 4: 跑 PASS**。
- [ ] **Step 5: commit** `feat(backend): 透传 subagent 事件 + subagent_id 到 SSE`。

---

## 阶段 1 收尾
- [ ] 全回归:`cd services/worker && uv run pytest -m "not docker" -q`;`cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker" -q`;common 测试。ruff。
- [ ] 对抗审查(Opus 子 agent,diff 内联):重点 emit 队列 drain/cancel 竞态、子 agent 失败不挂主回合、深度封顶不可绕过、provider 接线。
- [ ] 修复 → PR → CI → merge → 部署(worker+backend) → 生产 e2e(发一条让主 agent 调 task 的消息,worker 日志看 SubagentStarted/子事件/SubagentDone + task 工具结果)。

## Self-Review(spec 覆盖)
- 流式透传 ✓(Task 3 drain + Task 4 转发)。单一通用子 agent ✓(Task 4 `_SUBAGENT_SYSTEM` 通用模板)。深度封顶 1 ✓(Task 4 子用 inner 不含 task + Task 5 wiring 测)。串行 ✓(沿用 loop 串行循环)。共享 sandbox ✓(inner 即 SandboxToolExecutor 链)。token 累加 ✓(Task 4 accumulated_usage,server 在主 TurnDone 并入——补:Task 5 实现时在 RunTurnStream 收尾把 `executor.accumulated_usage` 加进 TurnDone.usage)。proto/事件/前端透传 ✓(Task 1/2/6;前端渲染属阶段 2)。
