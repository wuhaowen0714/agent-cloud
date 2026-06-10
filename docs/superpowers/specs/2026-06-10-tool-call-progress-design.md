# 工具调用进度指示(Codex 风)设计

**日期:** 2026-06-10
**状态:** 设计已批准

## 目标

LLM 流式生成工具调用参数期间(典型:write_file 大文件,32k token 输出可达分钟级),前端目前收不到任何事件,看似卡死——参数分片在 worker 被静默累积(`openai_provider.py` stream),直到流结束才发携带完整参数的 `ToolCallStarted`。改为全程展示轻量进度:**工具名 + 目标路径(若有)+ 已生成字符/行数**,不展示参数内容本身。覆盖所有工具。

## 设计

事件链 worker provider → loop → proto → backend SSE → 前端,每层加一小步;`server.py` / `runner.py` 经 codec 转换,零改动。

- **共享事件**(`packages/common/src/agent_cloud_common/events.py`):新增 `@dataclass ToolCallProgress { call_id, name, args_chars: int, lines: int, path_hint: str }`,加入 `TurnEvent` union。
- **proto**(`protos/agent_cloud/v1/worker.proto`):`TurnEvent` oneof 增第 6 支 `ToolCallProgress tool_call_progress = 6`(字段同上);`scripts/gen_protos.sh` 重新生成。wire 层向后兼容;但旧 backend 的 `turn_event_from_proto` 对未知 oneof 会 raise(回合失败)——backend 与 worker 共用同一镜像同滚,偏斜窗口仅秒级;若将来拆分滚动发布,须 backend 先行。
- **codec**(`packages/common/src/agent_cloud_common/codec.py`):`turn_event_to_proto` / `turn_event_from_proto` 各加一支(纯标量,无 JSON 负载)。
- **worker 数据源**(`openai_provider.py` stream 的 tool_call 分片累积处):按时间节流发 `ProviderToolCallProgress`(`provider.py` 新 dataclass,入 `ProviderEvent` union):
  - 发射门:`time.monotonic()` 距上次发射 ≥0.3s(**全局单计时器**,限制整体事件率;实际流里 call 串行到达,无需 per-call)、该 call 累积有增长、且 slot 的 id 与 name 均已知(OpenAI 兼容流首分片即带;未知则不发)。
  - `args_chars = len(slot["args"])`;`lines` = 累积串中 `\n` 转义序列数 + 1(JSON 转义换行 ≈ 内容行数;`\\n` 字面反斜杠会误计,进度提示可接受,注释说明)。
  - `path_hint`:首次在累积前缀上以 regex 提取 `"path"\s*:\s*"((?:[^"\\]|\\.)*)"`,命中即缓存不再扫;无 path 字段的工具(bash 等)为空串。不会误匹配 content 内出现的 `"path"` 文本:JSON 字符串值里的引号必转义为 `\"`,裸 `"path"` 只可能是真实键。
  - 流结束不补发(`ToolCallStarted` 紧随其后)。
- **loop**(`loop.py`):provider 事件 isinstance 分发加一支,透传为 `ToolCallProgress`。
- **backend SSE**(`turn/sse.py`):映射为 `{"type":"tool_call_progress","call_id","tool","args_chars","lines","path"}`。hub / runner / 落库零改动:progress 照常进回放缓冲(0.3s 节流下整回合至多几百条小字典,断线续看毫秒级快进),它不是消息、不落库。
- **前端**:
  - `types.ts`:新增 `tool_call_progress` 事件类型。
  - `blocks.ts`:`upsertToolProgress` —— 同 call_id 已是真卡(started)则忽略;已有 pending 卡则更新计数;否则追加 pending 卡。`appendToolCall` 升级:存在同 call_id 的 pending 卡时**原位替换**(保位置,不闪跳)。
  - `ToolCallCard` pending 态:工具名徽章 + path(若有)+「已生成 12.3k 字符 · 约 340 行」(行数 ≥2 才显示)+ 既有 spinner;无展开区、无结果区。
  - `ChatView` feed 分发加一支。`reset` 整组清 blocks,pending 卡随之消失;`error` / 流级异常终态**只剥 pending 卡**(`dropPendingTools`)——流已死不会再有 `tool_call_start` 升级它,留着会永久转圈;半截文本照旧保留(既有有意行为)。

## 限制(YAGNI)

- 进度事件不落库,回放不做去重/合并(量级可忽略)。
- 不展示参数内容增量;不做执行阶段(sandbox 写盘)进度——执行本身通常毫秒级。
- path 提取只认顶层 `"path"` 字段;bash 等无路径工具只显示计数。
- 非流式 RunTurn(一元)不涉及。

## 测试

- worker provider(假时钟 monkeypatch monotonic):0.3s 内多分片只发一次;id/name 未知不发;path 跨分片到达后首次提取并缓存;含转义的 path 正确;纯文本流零 progress;chars/lines 计数正确。
- codec:`ToolCallProgress` to_proto / from_proto 圆程。
- backend sse:映射字段齐全。
- 前端:blocks 的 upsert / 原位升级语义;ToolCallCard pending 渲染(徽章 / path / 计数 / spinner / 无展开);ChatView feed 分发;既有 resume 补播路径含 progress 事件不回归。
