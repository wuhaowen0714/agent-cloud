# Agent Cloud Sandbox

执行工具调用的 gRPC 服务(worker→sandbox 信任边界)。只暴露 `ExecTool`。

- `agent_cloud_sandbox.tools.run_tool(base, work_subdir, name, args_json)` — 执行一次工具(bash/write_file/read_file),带路径 containment。
- `agent_cloud_sandbox.server.create_server(base_workdir, host, port)` — 启动 aio gRPC 服务器。
- 契约见 `protos/agent_cloud/v1/sandbox.proto`;桩生成到 packages/common(`scripts/gen_protos.sh`)。
- 真实进程/文件系统隔离(microVM/gVisor + cgroups + egress)由部署层负责(spec §11),非本服务代码。

## 测试
```bash
cd services/sandbox && uv run pytest -v
```
