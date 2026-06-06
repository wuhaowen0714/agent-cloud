from __future__ import annotations

import uuid
from pathlib import Path


class InProcessProvisioner:
    """进程内 provisioner:每用户起一个 agent_cloud_sandbox aio 服务,
    每用户一个持久工作目录(durable 卷的本地替身)。仅单副本/开发用。
    懒导入 agent_cloud_sandbox,避免后端运行时强依赖 sandbox 包。
    """

    def __init__(self, base_root: Path) -> None:
        self._base_root = Path(base_root)
        self._servers: dict[uuid.UUID, object] = {}

    async def spawn(self, user_id: uuid.UUID) -> tuple[uuid.UUID, str]:
        from agent_cloud_sandbox.server import create_server

        sandbox_id = uuid.uuid4()
        workdir = self._base_root / str(user_id)
        workdir.mkdir(parents=True, exist_ok=True)
        server, port = await create_server(base_workdir=workdir, host="localhost", port=0)
        self._servers[sandbox_id] = server
        return sandbox_id, f"localhost:{port}"

    async def stop(self, sandbox_id: uuid.UUID) -> None:
        server = self._servers.pop(sandbox_id, None)
        if server is not None:
            await server.stop(None)
