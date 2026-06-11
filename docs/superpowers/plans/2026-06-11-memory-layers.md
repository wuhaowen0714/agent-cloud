# 记忆分层实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** remember/注入/自动提炼三处对齐 user(跨 agent)与 agent(专属)两层记忆语义,修复"agent 身份被写进 user 共享块"的污染。

**Architecture:** 见 spec `docs/superpowers/specs/2026-06-11-memory-layers-design.md`。proto 字段已预留,无 schema 变更;worker 改工具描述/渲染/提炼 prompt,backend 改提炼编排为双块读写。

**Tech Stack:** Python(worker/backend)+ pytest;前端不动。

---

### Task 1(A+B): remember spec + 注入渲染

**Files:** `services/worker/src/agent_cloud_worker/remember.py`、`context.py`;
Test: `services/worker/tests/test_remember.py`、`test_context.py`

- [ ] 失败测试:required 含 scope;缺 scope 执行仍成功(默认 user);`_render_memory`
      两节标题 + 块原文(不再 `- (scope)` 前缀)+ 只有一层时另一节不出现
- [ ] 实现 REMEMBER_SPEC 重写 + `_render_memory` 两节式
- [ ] `uv run pytest tests/test_remember.py tests/test_context.py` 绿;ruff
- [ ] commit `feat(worker): remember 分层引导 + 记忆注入两节式渲染`

### Task 2(C-worker): 双块 reconcile

**Files:** `services/worker/src/agent_cloud_worker/memory_extract.py`、`server.py`、
`protos/agent_cloud/v1/worker.proto`(仅注释)
Test: `services/worker/tests/test_memory_extract.py` + server 既有 ExtractMemory 用例

- [ ] 失败测试:`reconcile_memory` 双块都变/只 agent 变/changed=false echo 现值/缺
      `agent_changed` 键抛 MemoryParseError;handler 回填四字段
- [ ] 实现双块 prompt + `_parse` 四键校验 + `reconcile_memory` 签名;server 接线
- [ ] worker 全量 pytest 绿;ruff
- [ ] commit `feat(worker): 自动提炼升级双块(user+agent,错层归位)`

### Task 3(C-backend): 提炼编排双块读写

**Files:** `services/backend/src/agent_cloud_backend/turn/memory_extract.py`
Test: `services/backend/tests/test_memory_extract_orch.py`

- [ ] 失败测试:请求携带 agent 块现值;agent_changed=True → 写 agent 块
      (owner=agent_config_id,prune);任一块 MemoryConflict → 不推水位线
- [ ] 实现:读两块 → 请求带上 → 两个 changed 各自 write_version+prune,
      冲突 return False(整体回滚)
- [ ] backend 全量 RYUK pytest 绿;ruff
- [ ] commit `feat(backend): 记忆提炼编排双块读写`

### Task 4: 杂项 + 回归 + 审查 + PR

- [ ] README 智能体记忆行更新;proto 注释更新(若 Task 2 未含)
- [ ] worker + backend + frontend 三套全量
- [ ] Fable 5 对抗审查(diff 内联/文件),修复
- [ ] push + PR + CI → 等合并指令
