# 输出截断处理 + 上下文窗口配置 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** finish_reason=length 全链路处理(文本截断持久化提示 + 工具参数截断回合内自修复)+ max_tokens→32768 + 三预设模型窗口配置(75% 触发压缩)。

**Architecture:** worker 的 `ProviderCompleted` 扩展两个字段承载截断信息(worker 内部,不动 proto);loop 据此合成修复性 tool error 或上抛 `stop_reason="length"`;backend `_persist` 按 stop_reason 给截断文本追加标记;压缩阈值解析升级为「显式覆盖 → 窗口×ratio → 全局默认」。

**Tech Stack:** Python(worker/backend)+ pytest;README 配置表。

参考 spec:`docs/superpowers/specs/2026-06-10-length-handling-design.md`

---

## Task 1: provider 捕获 finish_reason + 残缺参数容忍(TDD)

**Files:** Modify `services/worker/src/agent_cloud_worker/provider.py`(ProviderCompleted 字段)、`openai_provider.py`;Test `services/worker/tests/test_openai_provider.py`

- [ ] Step 1 失败测试:`_delta` 夹具加 `finish_reason` 参数;三用例——length 置 `length_truncated`;残缺 args → `{}` + id 进 `truncated_call_ids`(含 id 缺失合成 `truncated-{index}`);complete 残缺 args 不崩。
- [ ] Step 2 实现(spec §1 代码);Step 3 `cd services/worker && uv run pytest tests/test_openai_provider.py -q` 全绿;Step 4 提交 `feat(worker): capture finish_reason; tolerate truncated tool-call args`

## Task 2: loop 自修复 + stop_reason="length"(TDD)

**Files:** Modify `services/worker/src/agent_cloud_worker/loop.py`;Test `services/worker/tests/test_loop.py`

- [ ] Step 1 失败测试(内联 fake provider 直接 yield 带截断信息的 `ProviderCompleted`):①截断 call → 无 executor 调用、`[tool-call truncated]` 错误结果、下一轮继续;②文本截断 → `TurnDone.stop_reason == "length"`。
- [ ] Step 2 实现(spec §2);Step 3 worker 全量 `uv run pytest -q`;Step 4 提交 `feat(worker): in-turn repair for truncated tool calls; stop_reason=length`

## Task 3: 配置(max_tokens 32768 + 窗口/ratio)(TDD)

**Files:** Modify `services/worker/src/agent_cloud_worker/config.py`、`services/backend/src/agent_cloud_backend/config.py`;Test `services/backend/tests/test_config_thresholds.py`(新)

- [ ] Step 1 失败测试:`compaction_threshold_for` 三级解析(显式覆盖 750→750;窗口×0.75:DeepSeek-V4-Pro→750_000、GLM-5.1→150_000;未知模型→128000)。
- [ ] Step 2 实现:worker `request_max_tokens=32768`;backend 加 `model_context_windows`/`compaction_trigger_ratio=0.75`,`compaction_threshold_for` 升级;Step 3 跑测;Step 4 提交 `feat(config): 32k output cap; per-model context windows drive compaction at 75%`

## Task 4: backend 截断标记(TDD)

**Files:** Modify `services/backend/src/agent_cloud_backend/turn/runner.py`(`_persist` + 调用点);Test `services/backend/tests/test_turn_runner.py`

- [ ] Step 1 失败测试:run_turn 收到 `stop_reason="length"` 的 TurnDone → 落库的最后一条 assistant 文本带「内容被截断」标记;`end_turn` 不带。
- [ ] Step 2 实现(spec §3);Step 3 backend 全量;Step 4 提交 `feat(backend): persist truncation notice when a turn ends on length`

## Task 5: README 配置表 + 回归 + 审查 + 收尾

- [ ] README:worker max_tokens 行默认改 32768;配置表加 `MODEL_CONTEXT_WINDOWS`(JSON)与 `COMPACTION_TRIGGER_RATIO` 两行。
- [ ] 前后端全量回归(前端无改动,跑一遍兜底)。
- [ ] Fable 5 对抗审查(重点:截断 call 的 history 合法性、repair 消息会不会引导出死循环、阈值解析优先级、标记是否会污染非文本收尾)。
- [ ] PR → CI 绿 → 等合并指令。
