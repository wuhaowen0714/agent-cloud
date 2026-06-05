# Agent Cloud Worker

agent 的"脑":回合循环 + provider 抽象 + 工具接口。纯库,无网络/DB。

- `run_turn(provider, executor, system=, history=, user_message=)` — 跑一个回合。
- `Provider` / `FakeProvider` — LLM 抽象;真实 provider 在后续 Plan 接入。
- `ToolExecutor` / `LocalToolExecutor` — 工具执行抽象;gRPC 沙箱执行器在 Plan 2b 实现同一接口。
- `build_system_prompt(...)` — 文档/记忆/技能 → 分层 system 文本。

## 测试
```bash
cd services/worker && uv run pytest -v   # 纯单元测试,无需 Docker
```
