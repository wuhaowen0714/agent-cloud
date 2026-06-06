import uuid

import grpc

from agent_cloud.v1 import sandbox_pb2, sandbox_pb2_grpc
from agent_cloud_backend.sandbox.inprocess import InProcessProvisioner


async def test_spawn_returns_reachable_sandbox(tmp_path):
    prov = InProcessProvisioner(base_root=tmp_path)
    user_id = uuid.uuid4()
    sandbox_id, endpoint = await prov.spawn(user_id)
    try:
        async with grpc.aio.insecure_channel(endpoint) as channel:
            stub = sandbox_pb2_grpc.SandboxStub(channel)
            resp = await stub.ExecTool(sandbox_pb2.ExecToolRequest(
                call_id="c1", tool_name="write_file",
                arguments_json='{"path": "a.txt", "content": "hi"}', work_subdir="s1"))
        assert resp.is_error is False
        # file landed in the per-user base workdir
        assert (tmp_path / str(user_id) / "s1" / "a.txt").read_text() == "hi"
    finally:
        await prov.stop(sandbox_id)


async def test_persistent_workdir_across_respawn(tmp_path):
    prov = InProcessProvisioner(base_root=tmp_path)
    user_id = uuid.uuid4()
    sid1, ep1 = await prov.spawn(user_id)
    async with grpc.aio.insecure_channel(ep1) as ch:
        await sandbox_pb2_grpc.SandboxStub(ch).ExecTool(sandbox_pb2.ExecToolRequest(
            call_id="c1", tool_name="write_file",
            arguments_json='{"path": "keep.txt", "content": "v"}', work_subdir="s1"))
    await prov.stop(sid1)
    # respawn same user -> same base workdir -> file persists
    sid2, ep2 = await prov.spawn(user_id)
    try:
        async with grpc.aio.insecure_channel(ep2) as ch:
            resp = await sandbox_pb2_grpc.SandboxStub(ch).ExecTool(sandbox_pb2.ExecToolRequest(
                call_id="c2", tool_name="read_file",
                arguments_json='{"path": "keep.txt"}', work_subdir="s1"))
        assert resp.content == "v"
    finally:
        await prov.stop(sid2)


async def test_stop_unknown_is_noop(tmp_path):
    prov = InProcessProvisioner(base_root=tmp_path)
    await prov.stop(uuid.uuid4())  # should not raise
