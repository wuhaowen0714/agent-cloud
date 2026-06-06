# Agent Cloud Backend

## 开发

```bash
# 起本地 Postgres
docker run -d --name agent-cloud-pg -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=agent_cloud -p 5432:5432 postgres:16

cd services/backend
uv run alembic upgrade head            # 迁移
uv run uvicorn agent_cloud_backend.main:app --reload   # 起服务
uv run pytest -v                       # 测试(需 Docker:testcontainers)
```

## 回合编排(Plan 2d)
- `POST /sessions/{id}/turn` `{ "content": "..." }` → 加会话锁 → 组装上下文 → gRPC 调 worker `RunTurn` → 落库新消息 → 返回 `{messages, stop_reason, usage}`。
- 配置:`AGENT_CLOUD_WORKER_ENDPOINT`、`AGENT_CLOUD_SANDBOX_ENDPOINT`(默认 localhost:50052 / 50051)。
- 当前为单一配置沙箱端点;每用户 sandbox 生命周期/路由见 Plan 4。流式见 Plan 3。
- 流式:`POST /sessions/{id}/turn/stream` `{ "content": "..." }` → `text/event-stream`(SSE)。逐事件下发 `text_delta`/`thinking_delta`/`tool_call_start`/`tool_result`,以 `turn_done`(含 `message_ids`/`usage`/`stop_reason`)收尾;错误以 `error` 事件 in-band 下发。后端代理 worker 的 `RunTurnStream`,`turn_done` 时落库新消息并释放锁。

## Sandbox 管理(Plan 4a)
- `SandboxManager.get_endpoint_for_user(user_id)` — 查 `SandboxRegistry`,命中则复用,否则经 `SandboxProvisioner` 起新 sandbox 并登记。`reap_idle()` 按 TTL 回收空闲 sandbox。
- `SandboxProvisioner` 是接口;`InProcessProvisioner`(每用户持久工作目录的进程内实现)仅单副本/开发用,生产用 Docker/k8s impl。
- 后端 turn 端点按用户路由(用 manager 取 endpoint)见 Plan 4b。
