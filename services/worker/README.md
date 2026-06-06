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

### 消息大小上限
- 服务端 channel/server 与 sandbox channel 都用共享常量
  `agent_cloud_common.MAX_GRPC_MESSAGE_BYTES`(32 MiB)放开 gRPC 默认 4 MB 上限,
  避免长回合的 `RunTurnResponse` 静默触发 `RESOURCE_EXHAUSTED`。
- **Plan 2d 后端的 Worker client channel 必须**用同样的 `options` 传入
  `MAX_GRPC_MESSAGE_BYTES`(尤其是接收侧 `grpc.max_receive_message_length`),
  否则服务端放行的大响应会在客户端按默认 4 MB 被截断为 `RESOURCE_EXHAUSTED`。

### 畸形请求的 gRPC 状态码
- 非法 `Msg.role`、坏 `arguments_json` → `INVALID_ARGUMENT`(client-fault)。
- `provider_factory` 失败(如未知 provider)→ `FAILED_PRECONDITION`。
- 其余非预期错误(如 `run_turn` 内部)仍按 `UNKNOWN` 冒泡,供 2d 后端区分
  永久性 client-fault 与瞬时 worker bug。
