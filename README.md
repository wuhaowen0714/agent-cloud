# Agent Cloud

无状态 Agent Cloud(monorepo)。设计见 `docs/superpowers/specs/`。

## 结构
- `services/backend` — 后端(FastAPI + 数据层),唯一访问 Postgres。
- `services/worker` — agent worker(后续)。
- `services/sandbox` — 沙箱运行时(后续)。
- `packages/common` — 跨服务共享库。
- `protos` — gRPC 契约(后续)。
- `frontend` / `apps` — Web / 原生端(后续)。

## 后端开发
见 `services/backend/README.md`。
