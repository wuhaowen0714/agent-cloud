# 工具调用进度指示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LLM 流式生成工具参数期间,前端实时显示「工具名 · 路径 · 已生成字符/行」,消除大 write 的假死感。

**Architecture:** worker provider 在参数分片累积处按 0.3s 全局节流发 `ProviderToolCallProgress` → loop 透传为共享事件 `ToolCallProgress` → proto oneof 第 6 支 → backend SSE `tool_call_progress` → 前端 pending 工具卡,`tool_call_start` 到达原位升级。`server.py`/`runner.py`/hub 经 codec 与回放缓冲,零改动。

**Tech Stack:** Python(dataclass + grpc protobuf + FastAPI SSE)、React19 + vitest。

参考 spec:`docs/superpowers/specs/2026-06-10-tool-call-progress-design.md`(已提交 92c215c)

注:Task 1–4 同分支原子合入——SSE 映射(Task 4)落地前 worker 不发进度(Task 2–3 同 PR),不存在中间态。

---

## Task 1: 共享事件 + proto + codec

**Files:**
- Modify: `packages/common/src/agent_cloud_common/events.py`
- Modify: `packages/common/src/agent_cloud_common/__init__.py`
- Modify: `protos/agent_cloud/v1/worker.proto`
- Modify: `packages/common/src/agent_cloud_common/codec.py`
- Test: `packages/common/tests/test_codec.py`

- [ ] **Step 1: 失败测试**(test_codec.py 末尾追加;`ToolCallProgress` 加入文件顶部 `from agent_cloud_common import (...)` 导入列表)

```python
def test_round_trip_tool_call_progress():
    e = ToolCallProgress(
        call_id="c1", name="write_file", args_chars=1234, lines=5, path_hint="src/a.py"
    )
    back = turn_event_from_proto(turn_event_to_proto(e))
    assert back == e
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd packages/common && uv run pytest tests/test_codec.py -q`
Expected: ImportError(`ToolCallProgress` 不存在)

- [ ] **Step 3: 实现**

`events.py` 在 `ToolCallStarted` 前插入,并更新 union:

```python
@dataclass
class ToolCallProgress:
    """工具调用参数生成中的节流进度(LLM 流式累积分片;不含参数内容本身)。"""

    call_id: str
    name: str
    args_chars: int
    lines: int
    path_hint: str
```

```python
TurnEvent = (
    TextDelta | ThinkingDelta | ToolCallProgress | ToolCallStarted | ToolResultEvent | TurnDone
)
```

`__init__.py`:`from agent_cloud_common.events import (...)` 列表与 `__all__` 各加 `"ToolCallProgress"`。

`worker.proto` 在 `ToolCallStarted` 消息后加:

```proto
message ToolCallProgress {
  string call_id = 1;
  string name = 2;
  int64 args_chars = 3;
  int64 lines = 4;
  string path_hint = 5;
}
```

`TurnEvent` oneof 加 `ToolCallProgress tool_call_progress = 6;`(放 `turn_done = 5` 之后)。

重新生成桩:`bash scripts/gen_protos.sh`

`codec.py`:事件导入加 `ToolCallProgress`;`turn_event_to_proto` 加分支:

```python
    if isinstance(event, ToolCallProgress):
        return worker_pb2.TurnEvent(
            tool_call_progress=worker_pb2.ToolCallProgress(
                call_id=event.call_id, name=event.name,
                args_chars=event.args_chars, lines=event.lines,
                path_hint=event.path_hint,
            )
        )
```

`turn_event_from_proto` 加分支:

```python
    if which == "tool_call_progress":
        t = proto.tool_call_progress
        return ToolCallProgress(
            call_id=t.call_id, name=t.name, args_chars=t.args_chars,
            lines=t.lines, path_hint=t.path_hint,
        )
```

- [ ] **Step 4: 测试过 + common 全量**

Run: `cd packages/common && uv run pytest -q`
Expected: 全 PASS

- [ ] **Step 5: 提交**

```bash
git add packages/common protos
git commit -m "feat(common): ToolCallProgress event + proto oneof + codec"
```

## Task 2: worker provider 节流发射进度

**Files:**
- Modify: `services/worker/src/agent_cloud_worker/provider.py`(dataclass + union)
- Modify: `services/worker/src/agent_cloud_worker/openai_provider.py`(stream 发射)
- Test: `services/worker/tests/test_openai_provider.py`

- [ ] **Step 1: 失败测试**(文件末尾追加;顶部已有 `_delta`/`_stream_client`/`_usage_chunk`/`_req` 工具)

```python
# ---- 工具调用参数生成进度(节流发射) ----
from agent_cloud_worker import openai_provider as op_mod  # noqa: E402
from agent_cloud_worker.provider import ProviderToolCallProgress  # noqa: E402


def _tc(index=0, id=None, name=None, arguments=None):
    return SimpleNamespace(
        index=index, id=id, function=SimpleNamespace(name=name, arguments=arguments)
    )


def _fake_clock(monkeypatch, times):
    it = iter(times)
    monkeypatch.setattr(op_mod, "_monotonic", lambda: next(it))


async def test_stream_emits_throttled_tool_progress(monkeypatch):
    # 三个参数分片,时刻 10.0/10.1/10.5:首片立即发,间隔 0.1s 的不发,0.5s 的发
    _fake_clock(monkeypatch, [10.0, 10.1, 10.5])
    frag1 = '{"path": "a.py", "content": "x'
    chunks = [
        _delta(tool_calls=[_tc(id="c1", name="write_file", arguments=frag1)]),
        _delta(tool_calls=[_tc(arguments="yz")]),
        _delta(tool_calls=[_tc(arguments='123"}')]),
        _usage_chunk(1, 1),
    ]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    prog = [e for e in events if isinstance(e, ProviderToolCallProgress)]
    assert len(prog) == 2
    assert prog[0].call_id == "c1" and prog[0].name == "write_file"
    assert prog[0].path_hint == "a.py"
    assert prog[0].args_chars == len(frag1)
    assert prog[1].args_chars == len('{"path": "a.py", "content": "xyz123"}')
    # 进度事件不影响最终装配
    done = events[-1]
    assert isinstance(done, ProviderCompleted)
    assert done.message.tool_calls[0].arguments == {"path": "a.py", "content": "xyz123"}


async def test_stream_progress_waits_for_id(monkeypatch):
    # id/name 分片未到不发(孤儿进度无法与 ToolCallStarted 配对);到齐才发
    _fake_clock(monkeypatch, [10.0, 20.0])
    chunks = [
        _delta(tool_calls=[_tc(arguments='{"comm')]),
        _delta(tool_calls=[_tc(id="c1", name="bash", arguments='and": "ls"}')]),
        _usage_chunk(1, 1),
    ]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    prog = [e for e in events if isinstance(e, ProviderToolCallProgress)]
    assert len(prog) == 1
    assert prog[0].call_id == "c1" and prog[0].name == "bash"


async def test_stream_progress_path_arrives_across_fragments(monkeypatch):
    # path 值的闭引号晚到:此前 path_hint 为空,到齐后提取并缓存
    _fake_clock(monkeypatch, [10.0, 20.0, 30.0])
    chunks = [
        _delta(tool_calls=[_tc(id="c1", name="write_file", arguments='{"pa')]),
        _delta(tool_calls=[_tc(arguments='th": "src/m')]),
        _delta(tool_calls=[_tc(arguments='ain.py", "content": "')]),
        _usage_chunk(1, 1),
    ]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    prog = [e for e in events if isinstance(e, ProviderToolCallProgress)]
    assert [p.path_hint for p in prog] == ["", "", "src/main.py"]


async def test_stream_progress_decodes_escaped_path(monkeypatch):
    _fake_clock(monkeypatch, [10.0])
    chunks = [
        _delta(tool_calls=[_tc(id="c1", name="write_file",
                               arguments='{"path": "we\\"ird.py", "content": "')]),
        _usage_chunk(1, 1),
    ]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    prog = [e for e in events if isinstance(e, ProviderToolCallProgress)]
    assert prog[0].path_hint == 'we"ird.py'


async def test_stream_progress_counts_lines(monkeypatch):
    _fake_clock(monkeypatch, [10.0])
    chunks = [
        _delta(tool_calls=[_tc(id="c1", name="write_file",
                               arguments='{"path": "a", "content": "l1\\nl2\\nl3')]),
        _usage_chunk(1, 1),
    ]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    prog = [e for e in events if isinstance(e, ProviderToolCallProgress)]
    assert prog[0].lines == 3  # 两个 \n 转义 + 1


async def test_stream_text_only_emits_no_progress():
    chunks = [_delta(content="he"), _delta(content="llo"), _usage_chunk(1, 1)]
    provider = OpenAIProvider(client=_stream_client(chunks), model="m", max_tokens=9)
    events = [e async for e in provider.stream(_req())]
    assert not any(isinstance(e, ProviderToolCallProgress) for e in events)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd services/worker && uv run pytest tests/test_openai_provider.py -q`
Expected: ImportError(`ProviderToolCallProgress` 不存在)

- [ ] **Step 3: 实现**

`provider.py` 在 `ProviderThinkingDelta` 后加 dataclass,并扩 union:

```python
@dataclass
class ProviderToolCallProgress:
    """LLM 正在生成某工具调用的参数(分片累积中,节流发射;不含内容)。"""

    call_id: str
    name: str
    args_chars: int
    lines: int
    path_hint: str
```

```python
ProviderEvent = (
    ProviderTextDelta | ProviderThinkingDelta | ProviderToolCallProgress | ProviderCompleted
)
```

`openai_provider.py` 顶部加 `import re`、`import time`,导入 `ProviderToolCallProgress`;模块级:

```python
_PROGRESS_INTERVAL = 0.3  # 进度事件最小间隔(秒):全局单计时器,限制整体事件率
_monotonic = time.monotonic  # 测试可替换的时钟
_PATH_RE = re.compile(r'"path"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _sniff_path(args_prefix: str) -> str:
    """从累积中的参数 JSON 前缀提取 "path" 字段值(进度展示用)。

    JSON 字符串值内的引号必转义为 \\"——裸 "path" 键只可能是真实键位,不会误匹配
    content 文本。值要取到闭引号才命中(中途返回 "",下次再试)。
    """
    m = _PATH_RE.search(args_prefix)
    if not m:
        return ""
    raw = m.group(1)
    try:
        return json.loads(f'"{raw}"')  # 解码 \\" \\\\ \\uXXXX 等转义
    except json.JSONDecodeError:
        return raw
```

`stream()` 内:`tool_acc` 槽位增加 `"path"` 键,循环前加 `last_progress = 0.0`;参数累积分支改为:

```python
        last_progress = 0.0  # 上次进度发射时刻;0 → 首个参数分片立即发

        async for chunk in stream:
            ...
            for tcd in delta.tool_calls or []:
                slot = tool_acc.setdefault(
                    tcd.index, {"id": "", "name": "", "args": "", "path": ""}
                )
                if tcd.id:
                    slot["id"] = tcd.id
                if tcd.function and tcd.function.name:
                    slot["name"] = tcd.function.name
                if tcd.function and tcd.function.arguments:
                    slot["args"] += tcd.function.arguments
                    now = _monotonic()
                    # 节流进度:id/name 已知(OpenAI 兼容流首分片即带)才发。
                    # 行数 = \n 转义数 + 1(字面 \\n 会误计,提示用途可接受)。
                    if slot["id"] and slot["name"] and now - last_progress >= _PROGRESS_INTERVAL:
                        if not slot["path"]:
                            slot["path"] = _sniff_path(slot["args"])
                        last_progress = now
                        yield ProviderToolCallProgress(
                            call_id=slot["id"],
                            name=slot["name"],
                            args_chars=len(slot["args"]),
                            lines=slot["args"].count("\\n") + 1,
                            path_hint=slot["path"],
                        )
```

(流结束不补发;末尾装配循环只读 `s["id"]/s["name"]/s["args"]`,多出的 `"path"` 键无影响。)

- [ ] **Step 4: 测试过 + worker 全量**

Run: `cd services/worker && uv run pytest -q`
Expected: 全 PASS(既有截断/装配测试对多出的进度事件不敏感——都按 `events[-1]`/isinstance 过滤断言)

- [ ] **Step 5: 提交**

```bash
git add services/worker
git commit -m "feat(worker): provider emits throttled tool-call progress during arg streaming"
```

## Task 3: loop 透传

**Files:**
- Modify: `services/worker/src/agent_cloud_worker/loop.py`
- Test: `services/worker/tests/test_loop.py`

- [ ] **Step 1: 失败测试**(test_loop.py 追加;顶部导入列表加 `ToolCallProgress`(agent_cloud_common)与 `ProviderToolCallProgress`(provider))

```python
async def test_stream_forwards_tool_progress(tmp_path):
    class _ProgressProvider:
        async def stream(self, request):
            yield ProviderToolCallProgress(
                call_id="c1", name="write_file", args_chars=120, lines=4, path_hint="a.py"
            )
            yield ProviderCompleted(
                message=Message(role=Role.ASSISTANT, text="done"),
                usage=Usage(input_tokens=1, output_tokens=1),
            )

    events = []
    async for e in run_turn_stream(
        _ProgressProvider(), _executor(tmp_path), system="", history=[], user_message="hi"
    ):
        events.append(e)
    prog = [e for e in events if isinstance(e, ToolCallProgress)]
    assert prog == [
        ToolCallProgress(call_id="c1", name="write_file", args_chars=120, lines=4, path_hint="a.py")
    ]
```

- [ ] **Step 2: 确认失败** — Run: `cd services/worker && uv run pytest tests/test_loop.py -q`,Expected: ImportError 或 prog == []

- [ ] **Step 3: 实现** — `loop.py`:common 导入块加 `ToolCallProgress`,provider 导入块加 `ProviderToolCallProgress`;stream 消费的 isinstance 链(TextDelta 分支后)加:

```python
            elif isinstance(event, ProviderToolCallProgress):
                yield ToolCallProgress(
                    call_id=event.call_id, name=event.name,
                    args_chars=event.args_chars, lines=event.lines,
                    path_hint=event.path_hint,
                )
```

- [ ] **Step 4: 测试过 + worker 全量** — Run: `cd services/worker && uv run pytest -q`,Expected: 全 PASS

- [ ] **Step 5: 提交**

```bash
git add services/worker
git commit -m "feat(worker): loop forwards tool-call progress events"
```

## Task 4: backend SSE 映射

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/turn/sse.py`
- Test: `services/backend/tests/test_sse.py`

- [ ] **Step 1: 失败测试**(test_sse.py 追加;顶部导入加 `ToolCallProgress`)

```python
def test_tool_call_progress_mapping():
    out = turn_event_to_sse(
        ToolCallProgress(call_id="c1", name="write_file", args_chars=1234, lines=5, path_hint="a.py")
    )
    assert out == {
        "type": "tool_call_progress",
        "call_id": "c1",
        "tool": "write_file",
        "args_chars": 1234,
        "lines": 5,
        "path": "a.py",
    }
```

- [ ] **Step 2: 确认失败** — Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_sse.py -q`,Expected: ValueError "unmapped streaming event"

- [ ] **Step 3: 实现** — `sse.py` 导入加 `ToolCallProgress`,`turn_event_to_sse` 加分支:

```python
    if isinstance(event, ToolCallProgress):
        return {
            "type": "tool_call_progress",
            "call_id": event.call_id,
            "tool": event.name,
            "args_chars": event.args_chars,
            "lines": event.lines,
            "path": event.path_hint,
        }
```

- [ ] **Step 4: 测试过** — Run: 同 Step 2,Expected: 全 PASS(backend 全量留 Task 7)

- [ ] **Step 5: 提交**

```bash
git add services/backend
git commit -m "feat(backend): map tool-call progress to SSE"
```

## Task 5: 前端 types + blocks(upsert / 原位升级)

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/blocks.ts`
- Test: `frontend/src/blocks.test.ts`

- [ ] **Step 1: 失败测试**(blocks.test.ts 追加;导入加 `upsertToolProgress`)

```ts
describe("upsertToolProgress / pending 升级", () => {
  const prog = (chars: number) => ({
    call_id: "c1", tool: "write_file", args_chars: chars, lines: 3, path: "a.py",
  })

  it("首个进度新开 pending 卡,后续原位更新计数", () => {
    let b: Block[] = []
    b = upsertToolProgress(b, prog(10))
    b = upsertToolProgress(b, prog(99))
    expect(b).toHaveLength(1)
    const t = b[0] as Extract<Block, { kind: "tool" }>
    expect(t.progress).toMatchObject({ argsChars: 99, lines: 3, path: "a.py" })
    expect(t.call.name).toBe("write_file")
  })

  it("tool_call_start 原位替换 pending 卡(位置与 id 不变,progress 清掉)", () => {
    let b: Block[] = []
    b = appendDelta(b, "text", "before")
    b = upsertToolProgress(b, prog(10))
    b = appendToolCall(b, { id: "c1", name: "write_file", arguments: { path: "a.py", content: "x" } })
    expect(b.map((x) => x.kind)).toEqual(["text", "tool"])
    const t = b[1] as Extract<Block, { kind: "tool" }>
    expect(t.progress).toBeUndefined()
    expect(t.call.arguments).toMatchObject({ path: "a.py" })
  })

  it("真卡之后迟到的进度被忽略(原引用返回)", () => {
    let b: Block[] = []
    b = appendToolCall(b, { id: "c1", name: "bash", arguments: { command: "ls" } })
    const out = upsertToolProgress(b, { call_id: "c1", tool: "bash", args_chars: 5, lines: 1, path: "" })
    expect(out).toBe(b)
  })

  it("appendToolCall 无 pending 时仍尾部追加(回归)", () => {
    let b: Block[] = []
    b = appendDelta(b, "text", "t")
    b = appendToolCall(b, { id: "c9", name: "bash", arguments: {} })
    expect(b.map((x) => x.kind)).toEqual(["text", "tool"])
  })
})
```

- [ ] **Step 2: 确认失败** — Run: `cd frontend && npx vitest run src/blocks.test.ts`,Expected: `upsertToolProgress` 未导出

- [ ] **Step 3: 实现**

`types.ts` 的 `TurnEvent` union 加(`tool_call_start` 行后):

```ts
  | { type: "tool_call_progress"; call_id: string; tool: string; args_chars: number; lines: number; path: string }
```

`blocks.ts`:

```ts
// 参数生成中的进度(tool 块的 pending 态;tool_call_start 升级真卡时清掉)
export interface ToolProgress { argsChars: number; lines: number; path: string }

export type Block =
  | { kind: "thinking"; id: string; text: string }
  | { kind: "text"; id: string; text: string }
  | { kind: "tool"; id: string; call: ToolCall; result?: ToolResult; progress?: ToolProgress }
```

```ts
// 流式:工具调用就地新开一块(以 call.id 为 key,稍后由结果回填)。
// 已有同 id 的 pending 进度卡(参数生成期间建的)→ 原位替换为真卡:保位置不闪跳,progress 清掉。
export function appendToolCall(blocks: Block[], call: ToolCall): Block[] {
  const i = blocks.findIndex((b) => b.kind === "tool" && b.id === call.id)
  if (i === -1) return [...blocks, { kind: "tool", id: call.id, call }]
  return [...blocks.slice(0, i), { kind: "tool", id: call.id, call }, ...blocks.slice(i + 1)]
}

// 流式:参数生成进度 upsert。已升级真卡 → 忽略迟到进度(原引用,零渲染);
// 已有 pending 卡 → 原位更新计数;否则尾部新开 pending 卡(参数未知,先空 {})。
export function upsertToolProgress(
  blocks: Block[],
  p: { call_id: string; tool: string; args_chars: number; lines: number; path: string },
): Block[] {
  const progress = { argsChars: p.args_chars, lines: p.lines, path: p.path }
  const i = blocks.findIndex((b) => b.kind === "tool" && b.id === p.call_id)
  if (i === -1) {
    return [
      ...blocks,
      { kind: "tool", id: p.call_id, call: { id: p.call_id, name: p.tool, arguments: {} }, progress },
    ]
  }
  const b = blocks[i] as Extract<Block, { kind: "tool" }>
  if (!b.progress) return blocks
  return [...blocks.slice(0, i), { ...b, progress }, ...blocks.slice(i + 1)]
}
```

- [ ] **Step 4: 测试过** — Run: `cd frontend && npx vitest run src/blocks.test.ts`,Expected: 全 PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/types.ts frontend/src/blocks.ts frontend/src/blocks.test.ts
git commit -m "feat(frontend): pending tool-progress blocks (upsert + in-place upgrade)"
```

## Task 6: ToolCallCard pending 态 + TurnBlocks/ChatView 接线

**Files:**
- Modify: `frontend/src/components/ToolCallCard.tsx`
- Modify: `frontend/src/components/TurnBlocks.tsx`
- Modify: `frontend/src/components/ChatView.tsx`
- Test: `frontend/src/components/ToolCallCard.test.tsx`

- [ ] **Step 1: 失败测试**(ToolCallCard.test.tsx 追加)

```tsx
  it("pending(参数生成中):显示路径与计数,无展开按钮与结果区", () => {
    render(
      <ToolCallCard
        call={{ id: "c9", name: "write_file", arguments: {} }}
        progress={{ argsChars: 12345, lines: 340, path: "src/big.py" }}
      />,
    )
    expect(screen.getByText("write_file")).toBeInTheDocument()
    expect(screen.getByText("src/big.py")).toBeInTheDocument()
    expect(screen.getByText("已生成 12.3k 字符 · 约 340 行")).toBeInTheDocument()
    expect(screen.queryByRole("button")).not.toBeInTheDocument()
  })

  it("pending 单行小参数:不显示行数,无路径不渲染路径", () => {
    render(
      <ToolCallCard
        call={{ id: "c8", name: "bash", arguments: {} }}
        progress={{ argsChars: 42, lines: 1, path: "" }}
      />,
    )
    expect(screen.getByText("已生成 42 字符")).toBeInTheDocument()
  })
```

- [ ] **Step 2: 确认失败** — Run: `cd frontend && npx vitest run src/components/ToolCallCard.test.tsx`,Expected: 断言失败(组件忽略未知 `progress` prop,找不到 "src/big.py" / 计数文案;`npm run lint` 此时也会报 prop 类型错)

- [ ] **Step 3: 实现**

`ToolCallCard.tsx`:导入 `import type { ToolProgress } from "../blocks"`;加格式化:

```tsx
function fmtChars(n: number): string {
  return n < 1000 ? `${n}` : `${(n / 1000).toFixed(1)}k`
}
```

组件签名与 pending 分支(放在现有 return 之前):

```tsx
export function ToolCallCard({
  call, result, progress,
}: { call: ToolCall; result?: ToolResult; progress?: ToolProgress }) {
  const [open, setOpen] = useState(false)
  const { summary, details } = describe(call)
  const error = result?.is_error ?? false

  if (progress) {
    // 参数生成中(LLM 流式累积):只给轻量进度,不渲染内容。ToolCallStarted 到达后
    // 上游原位替换为真卡(progress 清空),自然落回下方正常分支。
    const counter =
      `已生成 ${fmtChars(progress.argsChars)} 字符` +
      (progress.lines >= 2 ? ` · 约 ${progress.lines} 行` : "")
    return (
      <div className="my-1.5 overflow-hidden rounded-lg border border-l-2 border-slate-200 border-l-brand-200 bg-white text-xs">
        <div className="flex w-full items-center gap-2 px-2.5 py-1.5">
          <span className="shrink-0 rounded bg-brand-50 px-1.5 py-0.5 font-mono text-[11px] font-medium text-brand-700 ring-1 ring-brand-100">
            {call.name}
          </span>
          {progress.path && (
            <span className="min-w-0 truncate font-mono text-slate-600">{progress.path}</span>
          )}
          <span className="min-w-0 flex-1 truncate text-slate-400">{counter}</span>
          <span className="shrink-0" aria-hidden>
            <span className="block h-3 w-3 animate-spin rounded-full border-[1.5px] border-slate-200 border-t-brand-500" />
          </span>
        </div>
      </div>
    )
  }

  return ( /* 现有渲染原样保留 */ )
```

`TurnBlocks.tsx` 工具块行改为:

```tsx
        return <ToolCallCard key={b.id} call={b.call} result={b.result} progress={b.progress} />
```

`ChatView.tsx`:导入 `upsertToolProgress`(并入现有 blocks 导入),`feed` 的 `tool_call_start` 分支后加:

```tsx
    else if (e.type === "tool_call_progress")
      setLive((t) => ({ ...t, blocks: upsertToolProgress(t.blocks, e) }))
```

(feed 分支系 3 行胶水:字段由 `TurnEvent` 类型收窄编译期保证,行为由 blocks/card 测试覆盖,不单测。`reset`/`error` 整组清 blocks 的既有路径让 pending 卡自然消失,无需改动。)

- [ ] **Step 4: 测试过 + 前端全量 + lint**

Run: `cd frontend && npx vitest run && npm run lint`
Expected: 全 PASS;lint(tsc -b)零错误

- [ ] **Step 5: 提交**

```bash
git add frontend/src
git commit -m "feat(frontend): pending tool-call card with live progress counter"
```

## Task 7: 全量回归 + 对抗审查 + PR

- [ ] **全量回归**

```bash
cd packages/common && uv run pytest -q
cd ../../services/worker && uv run pytest -q
cd ../backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker" -q
cd ../.. && uv run ruff check packages services
cd frontend && npx vitest run && npm run lint
```

Expected: 全绿。

- [ ] **Fable 5 对抗审查**(Agent tool,`model: "fable"`,diff 内联)重点:节流时钟可测性与事件率上界;`_sniff_path` 正则的转义/跨分片边界与误匹配论证;回放缓冲增量量级;blocks 升级语义(迟到进度、resume 补播顺序);proto oneof 兼容性;ToolCallCard pending 与正常态切换。修复发现的问题并重跑相应测试。

- [ ] **PR**:推分支 → `gh pr create`(标题 `feat: live tool-call progress while args stream`)→ CI 绿 → 等用户合并指令。
