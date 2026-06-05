import pytest
from httpx import ASGITransport, AsyncClient

from agent_cloud_backend.main import create_app


@pytest.mark.asyncio
async def test_health_ok():
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
