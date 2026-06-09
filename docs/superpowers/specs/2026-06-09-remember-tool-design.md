# Agent 主动记忆:`remember` 工具 — 设计

**日期:** 2026-06-09 · **依赖:** 自整合单块记忆(`docs/superpowers/specs/2026-06-09-agent-memory-design.md`,已上线 main)

**目标:** 给 agent 一个 `remember(content, scope?)` 工具,让它在对话**当下主动**记下耐久事实 —— 与隐式的自动提炼互补(显式更准、更即时),并让 agent **自己指定 scope**,从而把之前搁置的"agent 层"用显式方式补上。

## 架构(方案 B:不加新通道、不改 proto、不改 loop)

- **`remember` 是 worker 原生工具**:在 worker 的 agent loop 内处理,**绝不转发沙箱**(沙箱不可信、无 DB)。用一个 `RememberingExecutor` 装饰现有 `SandboxToolExecutor`:
  - `specs()`:启用时在沙箱工具集之外**追加** `remember` 的 schema。
  - `execute(call)`:`name=="remember"` → 本地处理(校验参数、累计无关——见下、返回合成结果 `Remembered ✓`);其余 → 委托给内层(沙箱)。
- remember 的 **tool_call + tool_result 随正常 `new_messages` 流回**(助手消息的 tool_calls 里就带着它)。backend 本来就持久化 `new_messages`。
- **持久化(复用现有路径)**:backend 的 [`runner._persist`](../../../services/backend/src/agent_cloud_backend/turn/runner.py)(写 `new_messages` 的地方)**顺手扫描**助手 tool_calls 中 `name=="remember"` 的调用,对每个调 `MemoryEntryRepository.write_version` 把这条 fact 追加进对应块 —— **与写消息同一个 DB 事务**。owner 按 scope 解析(user→`user_id`,agent→`agent_config_id`,由 session 得到)。
- **边界全保住**:不需要 worker→backend 反向 RPC;DB 仍 backend 独占;沙箱永不碰记忆;`remember` 不调 LLM,key 不卷入。

```
agent → remember(content, scope)
  worker RememberingExecutor 拦下 → 返回 "Remembered ✓"(不进沙箱)
  → tool_call/result 进 new_messages → TurnDone → backend runner._persist
      ├─ 照常写消息
      └─ 扫到 remember 调用 → get_current → write_version(块 + "\n- " + content)   ← 同一事务
```

## 工具契约
- `name`: `remember`;参数:`content`(string,必填,非空)、`scope`(`"user"|"agent"`,默认 `"user"`)。
- 描述引导模型:**只记耐久、跨会话有用的**;`user`=关于这个人,`agent`=这个 agent 的活儿;临时/一次性的别记。

## 写入语义
- **追加**:`write_version(当前块 + "\n- " + content)`(无当前块则建首版)。去重/合并/裁剪交给已有的自动 reconcile(空闲/压缩时);软上限不变。
- 不在回合里跑 per-call LLM reconcile(省钱;auto-reconcile 兜底)。

## 启用
- 按 agent 经 `enabled_tools` 开关;前端 `BUILTIN_TOOLS` 加一项 `remember`(可勾选)。
- 空 `enabled_tools` = 全部(含 remember),与现有语义一致;worker 端强制(不只 prompt 隐藏)。

## 不在范围
- per-call LLM reconcile;调用频率硬限(靠描述引导 + 软上限 + 周期 reconcile);unary `RunTurn` 路径的 remember 落库(前端只用 streaming;按需再补)。

## 任务(TDD)
1. **worker**:`RememberingExecutor`(remember spec + 拦截 + 合成结果 + enabled 门);server.py 两处(RunTurn/RunTurnStream)包上。单测:specs 含/不含 remember、execute 拦截不进沙箱、参数校验、委托其余。
2. **backend**:`_persist` 应用 remember 调用 → `write_version`(owner 按 scope);抽成 helper(便于复用/测试)。单测:remember 调用 → 块追加;scope=agent → agent 块;无 remember → 不动;坏参数跳过。
3. **frontend**:`agentConfig.ts` BUILTIN_TOOLS 加 `remember`;AgentSettings 工具列表自然出现开关。前端测试沿用。
4. **全量回归 + 对抗审查(子 agent,diff 内联)+ 收尾分支**。
