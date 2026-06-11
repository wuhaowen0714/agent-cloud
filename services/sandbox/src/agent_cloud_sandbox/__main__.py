from __future__ import annotations

import asyncio
import os
from pathlib import Path

from agent_cloud_sandbox.server import create_server


async def _serve() -> None:
    base = Path(os.environ.get("AGENT_CLOUD_SANDBOX_BASE", "/tmp/agent-cloud-sandbox"))
    port = int(os.environ.get("AGENT_CLOUD_SANDBOX_PORT", "50051"))
    token = os.environ.get("AGENT_CLOUD_SANDBOX_TOKEN", "")  # 空=不校验(开发/旧镜像)
    base.mkdir(parents=True, exist_ok=True)
    server, bound_port = await create_server(
        base_workdir=base, host="0.0.0.0", port=port, token=token
    )
    print(f"sandbox listening on 0.0.0.0:{bound_port} (base={base})")
    await server.wait_for_termination()


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
