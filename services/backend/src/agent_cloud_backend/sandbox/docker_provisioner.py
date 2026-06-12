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
        worker_container: str = "",
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
        # network 模式:每沙箱起在专属网络,worker 动态接入(唯一需连沙箱的)。沙箱因此
        # 够不到 db/backend/邻居沙箱(跨租户隔离,spec B)。空 worker_container → spawn fail-loud。
        self._worker_container = worker_container
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

    async def alive(self, endpoint: str) -> bool:
        """探活(供 SandboxManager.health_check 注入)。

        network 模式:沙箱在专属网 acsbx-net-<id>,backend【不在】该网,从 backend 做 gRPC
        探活恒 timeout → 误判每个沙箱已死 → 每次 get_endpoint 都 mark_dead+重建,且每次撞
        新沙箱冷启动(worker 连未就绪的 server → refused)。改查 docker 容器是否 Running
        (backend 能访问 docker daemon),正确反映沙箱存活,沙箱真崩(容器 stopped/gone)
        才返回 False 触发重建。
        publish 模式(dev):沙箱端口发布到宿主 127.0.0.1,backend 经 localhost 可达,
        用 gRPC 连通性探(端点 = 127.0.0.1:<port>,无容器名可查)。
        """
        if self._network_mode == "network":
            name = endpoint.rsplit(":", 1)[0]  # acsbx-<id>:50051 → 容器名 acsbx-<id>
            return await asyncio.to_thread(self._container_running, name)
        from agent_cloud_backend.sandbox.health import grpc_endpoint_alive

        return await grpc_endpoint_alive(endpoint)

    def _container_running(self, name: str) -> bool:
        from docker.errors import NotFound

        try:
            return self._docker().containers.get(name).status == "running"
        except NotFound:
            return False  # 容器不存在 = 真死 → 触发重建
        except Exception:
            # docker daemon 瞬断等:不误杀健康沙箱(否则 mark_dead 后 stop 也失败 → 容器泄漏)。
            # fail-open 视为存活,下次探活自然恢复(审查 L1)。
            logger.exception("container running check errored for %s; assuming alive", name)
            return True

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
        net_name = f"acsbx-net-{sandbox_id}"
        client = self._docker()
        if self._network_mode == "network":
            if not self._worker_container:
                raise ValueError("network 模式需配置 sandbox_worker_container(worker 容器名)")
            # 专属网络:沙箱只在此网,与 db/backend/邻居沙箱物理隔离(spec B)。
            await asyncio.to_thread(
                client.networks.create, net_name, driver="bridge", labels={"managed-by": _LABEL}
            )
            kwargs["network"] = net_name
            endpoint = f"{name}:{_SANDBOX_PORT}"
        else:  # publish:发布随机宿主端口,worker 在宿主连 localhost
            kwargs["ports"] = {f"{_SANDBOX_PORT}/tcp": None}
            endpoint = ""
        try:
            container = await asyncio.to_thread(client.containers.run, **kwargs)
        except Exception:
            if self._network_mode == "network":
                await self._remove_network(net_name)  # 容器没起来 → 清掉刚建的空网络
            raise
        # run 之后任何失败都把容器(+网络)清掉,避免「在跑却没登记」的孤儿(reaper 只看 DB registry)。
        try:
            if self._network_mode == "network":
                # worker 接入专属网络 → 能连沙箱;沙箱仍够不到别的网络。
                net = await asyncio.to_thread(client.networks.get, net_name)
                await asyncio.to_thread(net.connect, self._worker_container)
            else:
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
            if self._network_mode == "network":
                await self._remove_network(net_name)
            raise
        logger.info("spawned sandbox %s for user %s at %s", sandbox_id, user_id, endpoint)
        return sandbox_id, endpoint, token

    async def _remove_network(self, net_name: str) -> None:
        """断开所有接入容器并删网络(best-effort)。worker 多宿在多个 acsbx-net 上,
        删本网前需先 disconnect 它,否则 network.remove 因「有活动端点」失败。"""
        client = self._docker()

        def _rm() -> None:
            from docker.errors import NotFound

            try:
                net = client.networks.get(net_name)
            except NotFound:
                return
            try:
                net.reload()
                for c in net.containers:
                    try:
                        net.disconnect(c, force=True)
                    except Exception:
                        logger.exception("failed to disconnect %s from %s", c, net_name)
                net.remove()
            except Exception:
                logger.exception("failed to remove sandbox network %s", net_name)

        await asyncio.to_thread(_rm)

    async def stop(self, sandbox_id: uuid.UUID) -> None:
        name = f"acsbx-{sandbox_id}"
        client = self._docker()

        def _stop() -> None:
            from docker.errors import NotFound

            try:
                c = client.containers.get(name)
            except NotFound:
                c = None  # 容器已不在;仍尝试清网络(可能半起留下空网)
            if c is not None:
                try:
                    c.stop(timeout=5)
                finally:
                    c.remove(force=True)

        await asyncio.to_thread(_stop)
        # network 模式:断开 worker 并删专属网络(publish 模式无此网,_remove_network 直接 no-op)
        if self._network_mode == "network":
            await self._remove_network(f"acsbx-net-{sandbox_id}")

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
            # 清理 per-sandbox 网络(按 label;先 disconnect 残留容器再 remove)
            for net in client.networks.list(filters={"label": f"managed-by={_LABEL}"}):
                if not net.name.startswith("acsbx-net-"):
                    continue
                try:
                    net.reload()
                    for cont in net.containers:
                        try:
                            net.disconnect(cont, force=True)
                        except Exception:
                            logger.exception("failed to disconnect %s from %s", cont, net.name)
                    net.remove()
                except Exception:
                    logger.exception("failed to remove sandbox network %s", net.name)

        await asyncio.to_thread(_all)
