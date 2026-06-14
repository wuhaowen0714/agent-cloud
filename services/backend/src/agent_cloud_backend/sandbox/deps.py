from __future__ import annotations

from pathlib import Path

from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.sandbox.docker_provisioner import DockerProvisioner
from agent_cloud_backend.sandbox.inprocess import InProcessProvisioner
from agent_cloud_backend.sandbox.manager import SandboxManager
from agent_cloud_backend.sandbox.provisioner import SandboxProvisioner

_manager: SandboxManager | None = None


def build_provisioner(settings: Settings, docker_client=None) -> SandboxProvisioner:
    """按配置造 provisioner。docker_client 仅测试注入(避免连真 Docker)。"""
    if settings.sandbox_provisioner == "docker":
        return DockerProvisioner(
            host_root=settings.effective_sandbox_host_root,
            image=settings.sandbox_image,
            network_mode=settings.sandbox_docker_network_mode,
            worker_container=settings.sandbox_worker_container,
            mem_limit=settings.sandbox_mem_limit,
            nano_cpus=settings.sandbox_nano_cpus,
            pids_limit=settings.sandbox_pids_limit,
            allow_net=settings.sandbox_allow_net,
            timezone=settings.sandbox_timezone,
            client=docker_client,
        )
    return InProcessProvisioner(base_root=Path(settings.sandbox_base_root))


def get_sandbox_manager() -> SandboxManager:
    """进程级单例 SandboxManager(provisioner 持有沙箱句柄,故必须单例)。
    测试通过 app.dependency_overrides[get_sandbox_manager] 注入自己的 manager。"""
    global _manager
    if _manager is None:
        settings = get_settings()
        provisioner = build_provisioner(settings)
        # health_check 注入:端点死亡(backend 重启 / 沙箱崩溃)会被探活发现并重建,
        # 而非复用陈旧端点导致 UNAVAILABLE。docker provisioner 用自己的 alive(network 模式
        # 查容器 Running——backend 不在沙箱专属网,gRPC 探恒 timeout 会误判每个沙箱已死、
        # 疯狂重建);inprocess 恒活,无需注入(None)。
        # hasattr 而非 isinstance:provisioner 被 wrapper/proxy 包一层也不会静默退化为 None
        # (那会让沙箱真死后端点永久复用,审查 L2)。
        health_check = getattr(provisioner, "alive", None)
        _manager = SandboxManager(
            provisioner=provisioner,
            sessionmaker=get_sessionmaker(),
            idle_ttl_seconds=settings.sandbox_idle_ttl_seconds,
            health_check=health_check,
        )
    return _manager
