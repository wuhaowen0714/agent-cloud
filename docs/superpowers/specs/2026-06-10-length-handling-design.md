# 输出截断(finish_reason=length)处理 + 上下文窗口配置设计

**日期:** 2026-06-10
**状态:** 设计已批准(用户指定参数:max_tokens=32768;三预设模型窗口 1M/1M/200k;75% 触发压缩)

## 背景(现状缺陷)

`finish_reason="length"` 全链路被忽略:① 纯文本截断 → `end_turn` 静默"成功",用户看到半截话无提示;② 工具调用参数 JSON 被掐断 → provider `json.loads` 抛 `JSONDecodeError` → gRPC INTERNAL → backend 按 transient 重试 3 次(确定性复现)→ 「the turn failed」,根因不可见。

## 设计

### 1. worker:provider 捕获 finish_reason + 容忍残缺工具参数

`ProviderCompleted` 扩展(worker 内部类型,不动 common/proto):

```python
@dataclass
class ProviderCompleted:
    message: Message
    usage: Usage
    length_truncated: bool = False          # finish_reason == "length"
    truncated_call_ids: set[str] = field(default_factory=set)  # 参数 JSON 解析失败的 call
```

`openai_provider.stream()`:
- 逐 chunk 记录最后一个非空 `choices[0].finish_reason`;
- 收尾组装 tool_calls 时,`json.loads` 失败的 slot **不再抛**:`arguments={}`、call id 进 `truncated_call_ids`(id 为空时合成 `truncated-{index}`);
- `length_truncated = (finish == "length")`。

`complete()`(一元路径,仅止血):`message_from_openai` 对单个 call 的参数解析失败降级为 `arguments={}`,不再让整个请求崩成 INTERNAL(不做回合内修复——生产路径是流式)。

### 2. worker:loop 回合内自修复 + `stop_reason="length"`

`run_turn_stream`:
- 无 tool_calls 收尾时:`stop_reason = "length" if completed.length_truncated else "end_turn"`(词表新增 `length`;proto/codec 是自由字符串,直通)。
- 执行工具时,`call.id ∈ truncated_call_ids` 的**跳过 executor**,合成错误结果回灌(模型据此在回合内重试小块写入):

```
[tool-call truncated] The arguments for this call were cut off because the
response hit the per-request output token limit (finish_reason=length).
Re-issue the call with a smaller payload — e.g. write the file in smaller
chunks across multiple calls.
```

(history 合法性:assistant 消息保留该 call(`arguments={}`),tool 消息按 call_id 应答 ✓)

### 3. backend:文本截断的持久化提示

`runner._persist` 增加 `stop_reason` 参数;`stop_reason == "length"` 时,给本回合**最后一条带文本的 assistant 消息**追加一行(落库前,随消息持久、刷新仍在,前端 markdown 渲染斜体,零前端改动):

```
\n\n*(输出已达单次 token 上限,内容被截断——可输入「继续」接着生成)*
```

### 4. 配置

- worker `request_max_tokens`:**4096 → 32768**。
- backend 新增(阈值解析顺序:显式 `compaction_token_thresholds` 覆盖 → `窗口 × ratio` → 全局默认):

```python
model_context_windows: dict[str, int] = {
    "DeepSeek-V4-Pro": 1_000_000,
    "DeepSeek-V4-Flash": 1_000_000,
    "GLM-5.1": 200_000,
}
compaction_trigger_ratio: float = 0.75   # 阈值 = 窗口 × 0.75
```

即三模型的自动压缩阈值:750k / 750k / 150k tokens;未配置窗口的模型回退 `compaction_token_threshold`(128000)。

- README 配置表同步(max_tokens 默认值、两个新变量)。

## 非目标(YAGNI)

自动续写(检测 length 自动发"继续"拼接)、一元 RunTurn 的回合内修复、按 provider 探测真实窗口。

## 测试

- worker provider:stream 收到 `finish_reason="length"` → `length_truncated`;残缺参数 → `arguments={}` + id 进集合、不抛;complete 残缺参数不崩。
- worker loop:截断 call → executor 不被调、回灌 `[tool-call truncated]` 错误、回合继续;纯文本截断 → `TurnDone.stop_reason == "length"`。
- backend:`compaction_threshold_for` 三级解析(覆盖 > 窗口×ratio > 默认);`_persist` 在 `stop_reason="length"` 时追加标记、其它不追加。
