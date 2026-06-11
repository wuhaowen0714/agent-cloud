from __future__ import annotations

import asyncio
import logging
import os
import secrets
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
        if not allow_net:
            # 出网限制是网络层的事(internal network / 出网代理 / 域名 allowlist),
            # 单靠 docker run 标志在 publish/network 两模式下都做不到(network_disabled
            # 会同时断掉 worker→沙箱)。不静默假装支持 → fail-loud,避免虚假安全(spec §9)。
            raise ValueError(
                "sandbox_allow_net=False 暂未在 provisioner 层强制;请保持 ALLOW_NET=true,"
                "并在部署网络层收紧出网(internal network / 出网代理 / allowlist)。"
            )
        self._host_root = str(host_root)
        self._image = image
        self._network_mode = network_mode
        self._network = network
        self._mem_limit = mem_limit
        self._nano_cpus = nano_cpus
        self._pids_limit = pids_limit
        # 懒连:None 时首次 spawn 才 docker.from_env(),daemon 不可达不致 backend 启动即崩。
        self._client = client

    def _docker(self):
        if self._client is None:
            import docker

            self._client = docker.from_env()
        return self._client

    async def spawn(self, user_id: uuid.UUID) -> tuple[uuid.UUID, str, str]:
        sandbox_id = uuid.uuid4()
        name = f"acsbx-{sandbox_id}"
        host_ws = f"{self._host_root}/{user_id}/workspace"
        os.makedirs(host_ws, exist_ok=True)  # bind 源目录必须存在
        # 每沙箱一个随机 gRPC 鉴权 token,注入容器 env;沙箱 server 据此校验调用方,
        # worker 经 RunTurnRequest.sandbox_token 拿到并在 metadata 带上(spec C②)。
        token = secrets.token_urlsafe(32)
        kwargs: dict = dict(
            image=self._image,
            detach=True,
            name=name,
            environment={"AGENT_CLOUD_SANDBOX_TOKEN": token},
            volumes={host_ws: {"bind": "/workspace", "mode": "rw"}},
            labels={"managed-by": _LABEL, "user_id": str(user_id)},
            mem_limit=self._mem_limit,
            memswap_limit=self._mem_limit,  # 禁 swap(否则默认 memswap=2×mem,上限被悄悄翻倍)
            nano_cpus=self._nano_cpus,
            pids_limit=self._pids_limit,
            tmpfs={"/tmp": "rw,size=128m"},  # /tmp 走 tmpfs,不落容器可写层、限大小
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
        )
        if self._network_mode == "network":
            kwargs["network"] = self._network
            endpoint = f"{name}:{_SANDBOX_PORT}"
        else:  # publish:发布随机宿主端口,worker 在宿主连 localhost
            kwargs["ports"] = {f"{_SANDBOX_PORT}/tcp": None}
            endpoint = ""
        client = self._docker()
        container = await asyncio.to_thread(client.containers.run, **kwargs)
        # run 之后任何失败都把容器清掉,避免「在跑却没登记」的孤儿(reaper 只看 DB registry)。
        try:
            if self._network_mode != "network":
                await asyncio.to_thread(container.reload)
                mappings = container.ports.get(f"{_SANDBOX_PORT}/tcp") or []
                if not mappings:
                    raise RuntimeError(f"sandbox {name} did not publish a host port")
                endpoint = f"127.0.0.1:{mappings[0]['HostPort']}"
        except Exception:
            try:
                await asyncio.to_thread(container.remove, force=True)
            except Exception:
                logger.exception("failed to remove half-spawned sandbox %s", name)
            raise
        logger.info("spawned sandbox %s for user %s at %s", sandbox_id, user_id, endpoint)
        return sandbox_id, endpoint, token

    async def stop(self, sandbox_id: uuid.UUID) -> None:
        name = f"acsbx-{sandbox_id}"
        client = self._docker()

        def _stop() -> None:
            from docker.errors import NotFound

            try:
                c = client.containers.get(name)
            except NotFound:
                return  # 已不在 → no-op(Protocol 要求未知 id 视为 no-op)
            try:
                c.stop(timeout=5)
            finally:
                c.remove(force=True)

        await asyncio.to_thread(_stop)

    async def stop_all(self) -> None:
        """停掉本系统起的所有沙箱容器(测试 teardown / 运维清理)。按 label 找。"""
        client = self._docker()

        def _all() -> None:
            for c in client.containers.list(all=True, filters={"label": f"managed-by={_LABEL}"}):
                try:
                    c.stop(timeout=5)
                    c.remove(force=True)
                except Exception:
                    logger.exception("failed to stop sandbox container %s", getattr(c, "name", "?"))

        await asyncio.to_thread(_all)
