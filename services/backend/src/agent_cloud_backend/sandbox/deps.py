from __future__ import annotations

from pathlib import Path

from agent_cloud_backend.config import get_settings
from agent_cloud_backend.db import get_sessionmaker
from agent_cloud_backend.sandbox.health import grpc_endpoint_alive
from agent_cloud_backend.sandbox.inprocess import InProcessProvisioner
from agent_cloud_backend.sandbox.manager import SandboxManager

_manager: SandboxManager | None = None


def get_sandbox_manager() -> SandboxManager:
    """进程级单例 SandboxManager(provisioner 持有进程内沙箱句柄,故必须单例)。
    测试通过 app.dependency_overrides[get_sandbox_manager] 注入自己的 manager。"""
    global _manager
    if _manager is None:
        settings = get_settings()
        provisioner = InProcessProvisioner(base_root=Path(settings.sandbox_base_root))
        # 注入探活:端点死亡(backend 重启后进程内沙箱随旧进程消失、或真实沙箱崩溃)会被
        # 发现并重建,而非复用陈旧端点导致每个工具调用 "sandbox RPC failed: UNAVAILABLE"。
        _manager = SandboxManager(
            provisioner=provisioner,
            sessionmaker=get_sessionmaker(),
            health_check=grpc_endpoint_alive,
        )
    return _manager
