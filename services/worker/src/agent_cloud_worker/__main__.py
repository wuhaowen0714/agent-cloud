from __future__ import annotations

import asyncio
import logging

from agent_cloud_worker.config import get_worker_settings
from agent_cloud_worker.factory import build_provider_factory
from agent_cloud_worker.server import create_server

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_worker_settings()
    factory = build_provider_factory(settings)
    server, port = await create_server(
        provider_factory=factory, host=settings.grpc_host, port=settings.grpc_port
    )
    logger.info("agent-cloud worker listening on %s:%s", settings.grpc_host, port)
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(main())
