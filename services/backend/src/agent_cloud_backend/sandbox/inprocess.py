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

    async def spawn(self, user_id: uuid.UUID) -> tuple[uuid.UUID, str, str]:
        from agent_cloud_sandbox.server import create_server

        sandbox_id = uuid.uuid4()
        workdir = self._base_root / str(user_id)
        workdir.mkdir(parents=True, exist_ok=True)
        server, port = await create_server(base_workdir=workdir, host="localhost", port=0)
        self._servers[sandbox_id] = server
        return sandbox_id, f"localhost:{port}", ""  # 进程内无隔离需求 → 空 token(server 开放)

    async def stop(self, sandbox_id: uuid.UUID) -> None:
        server = self._servers.pop(sandbox_id, None)
        if server is not None:
            await server.stop(None)

    async def stop_all(self) -> None:
        """停掉所有已起的 sandbox 服务并清空登记。

        测试 teardown 用:未停的 aio server 会泄漏到解释器退出时被 GC 终结,
        抛 'Event loop is closed' / 'AioServer.shutdown was never awaited',
        进而挂死整进程(整套 backend 测试一次跑不完的根因)。
        """
        for server in self._servers.values():
            await server.stop(None)
        self._servers.clear()
