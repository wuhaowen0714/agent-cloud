from __future__ import annotations

import asyncio
import logging
import os
import uuid

logger = logging.getLogger(__name__)

_SANDBOX_PORT = "50051"
_LABEL = "agent-cloud"


class DockerProvisioner:
    """借宿主 Docker daemon 起每用户沙箱容器(DooD)。实现 SandboxProvisioner Protocol。

    隔离:容器只挂载该用户的 <host_root>/<user_id>/workspace 到 /workspace,宿主机其它
    用户目录在容器内不存在 → 跨用户越权读取被堵(spec §1/§9)。docker SDK 是同步的,
    全部调用包进 asyncio.to_thread 以不阻塞事件循环。
    """

    def __init__(
        self,
        *,
        host_root: str,
        image: str,
        network_mode: str = "publish",
        network: str = "agent-cloud-net",
        mem_limit: str = "512m",
        nano_cpus: int = 1_000_000_000,
        pids_limit: int = 256,
        allow_net: bool = True,
        client=None,
    ) -> None:
        self._host_root = str(host_root)
        self._image = image
        self._network_mode = network_mode
        self._network = network
        self._mem_limit = mem_limit
        self._nano_cpus = nano_cpus
        self._pids_limit = pids_limit
        self._allow_net = allow_net
        if client is None:
            import docker

            client = docker.from_env()
        self._client = client

    async def spawn(self, user_id: uuid.UUID) -> tuple[uuid.UUID, str]:
        sandbox_id = uuid.uuid4()
        name = f"acsbx-{sandbox_id}"
        host_ws = f"{self._host_root}/{user_id}/workspace"
        os.makedirs(host_ws, exist_ok=True)  # bind 源目录必须存在
        kwargs: dict = dict(
            image=self._image,
            detach=True,
            name=name,
            volumes={host_ws: {"bind": "/workspace", "mode": "rw"}},
            labels={"managed-by": _LABEL, "user_id": str(user_id)},
            mem_limit=self._mem_limit,
            nano_cpus=self._nano_cpus,
            pids_limit=self._pids_limit,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
        )
        if self._network_mode == "network":
            kwargs["network"] = self._network
            endpoint = f"{name}:{_SANDBOX_PORT}"
        else:  # publish:发布随机宿主端口,worker 在宿主连 localhost
            kwargs["ports"] = {f"{_SANDBOX_PORT}/tcp": None}
            endpoint = ""
        container = await asyncio.to_thread(self._client.containers.run, **kwargs)
        if self._network_mode != "network":
            await asyncio.to_thread(container.reload)
            host_port = container.ports[f"{_SANDBOX_PORT}/tcp"][0]["HostPort"]
            endpoint = f"127.0.0.1:{host_port}"
        logger.info("spawned sandbox %s for user %s at %s", sandbox_id, user_id, endpoint)
        return sandbox_id, endpoint

    async def stop(self, sandbox_id: uuid.UUID) -> None:
        name = f"acsbx-{sandbox_id}"

        def _stop() -> None:
            from docker.errors import NotFound

            try:
                c = self._client.containers.get(name)
            except NotFound:
                return  # 已不在 → no-op(Protocol 要求未知 id 视为 no-op)
            try:
                c.stop(timeout=5)
            finally:
                c.remove(force=True)

        await asyncio.to_thread(_stop)

    async def stop_all(self) -> None:
        """停掉本系统起的所有沙箱容器(测试 teardown / 运维清理)。按 label 找。"""

        def _all() -> None:
            for c in self._client.containers.list(
                all=True, filters={"label": f"managed-by={_LABEL}"}
            ):
                try:
                    c.stop(timeout=5)
                    c.remove(force=True)
                except Exception:
                    logger.exception("failed to stop sandbox container %s", getattr(c, "name", "?"))

        await asyncio.to_thread(_all)
