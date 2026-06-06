from __future__ import annotations

import uuid
from typing import Protocol


class SandboxProvisioner(Protocol):
    """提供/销毁 sandbox 的抽象。生产用 Docker/k8s 实现;本仓库提供进程内实现。"""

    async def spawn(self, user_id: uuid.UUID) -> tuple[uuid.UUID, str]:
        """起一个 sandbox,返回 (sandbox_id, endpoint)。"""
        ...

    async def stop(self, sandbox_id: uuid.UUID) -> None:
        """停掉一个 sandbox(未知 id 视为 no-op)。"""
        ...
