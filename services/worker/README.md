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

## gRPC 服务器(Plan 2c)
- `agent_cloud_worker.server.create_server(provider_factory, host, port)` — 启动 `Worker` aio gRPC 服务,实现 `RunTurn`。
- 契约:`protos/agent_cloud/v1/worker.proto`(`RunTurnRequest/Response`)。
- `provider_factory(model, provider, key_ref) -> Provider`:由 agent 配置造 provider(真实 LLM provider 后续接入)。
- 后端编排(会话锁/上下文组装/落库)见 Plan 2d。
