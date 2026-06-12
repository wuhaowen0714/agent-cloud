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
        provider_factory=factory,
        host=settings.grpc_host,
        port=settings.grpc_port,
        network_region=settings.network_region,
        max_iterations=settings.max_iterations,
        timezone_offset_hours=settings.timezone_offset_hours,
        web_search_endpoint=settings.web_search_endpoint,
        web_search_api_key=settings.web_search_api_key,
        web_search_max_results=settings.web_search_max_results,
        image_gen_endpoint=settings.image_gen_endpoint,
        # 留空回退到 web_search 的同一 sophnet 平台 key(用户只配一个 key 即可两用)。
        image_gen_api_key=settings.image_gen_api_key or settings.web_search_api_key,
        image_gen_model=settings.image_gen_model,
    )
    logger.info("agent-cloud worker listening on %s:%s", settings.grpc_host, port)
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(main())
