import uuid

from agent_cloud_backend.sandbox.health import grpc_endpoint_alive
from agent_cloud_backend.sandbox.inprocess import InProcessProvisioner


async def test_alive_true_for_live_sandbox(tmp_path):
    prov = InProcessProvisioner(base_root=tmp_path)
    sandbox_id, endpoint = await prov.spawn(uuid.uuid4())
    try:
        assert await grpc_endpoint_alive(endpoint) is True
    finally:
        await prov.stop(sandbox_id)


async def test_alive_false_for_dead_endpoint():
    # 没有服务在 localhost:1 监听 -> 连接被拒/超时 -> False(快速,timeout 兜底)
    assert await grpc_endpoint_alive("localhost:1", timeout=0.5) is False
