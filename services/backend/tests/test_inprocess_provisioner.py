import uuid

import grpc
from agent_cloud.v1 import sandbox_pb2, sandbox_pb2_grpc
from agent_cloud_backend.sandbox.inprocess import InProcessProvisioner


async def test_spawn_returns_reachable_sandbox(tmp_path):
    prov = InProcessProvisioner(base_root=tmp_path)
    user_id = uuid.uuid4()
    sandbox_id, endpoint, _ = await prov.spawn(user_id)
    try:
        async with grpc.aio.insecure_channel(endpoint) as channel:
            stub = sandbox_pb2_grpc.SandboxStub(channel)
            resp = await stub.ExecTool(
                sandbox_pb2.ExecToolRequest(
                    call_id="c1",
                    tool_name="write_file",
                    arguments_json='{"path": "a.txt", "content": "hi"}',
                    work_subdir="s1",
                )
            )
        assert resp.is_error is False
        # file landed in the per-user base workdir
        assert (tmp_path / str(user_id) / "s1" / "a.txt").read_text() == "hi"
    finally:
        await prov.stop(sandbox_id)


async def test_persistent_workdir_across_respawn(tmp_path):
    prov = InProcessProvisioner(base_root=tmp_path)
    user_id = uuid.uuid4()
    sid1, ep1, _ = await prov.spawn(user_id)
    async with grpc.aio.insecure_channel(ep1) as ch:
        await sandbox_pb2_grpc.SandboxStub(ch).ExecTool(
            sandbox_pb2.ExecToolRequest(
                call_id="c1",
                tool_name="write_file",
                arguments_json='{"path": "keep.txt", "content": "v"}',
                work_subdir="s1",
            )
        )
    await prov.stop(sid1)
    # respawn same user -> same base workdir -> file persists
    sid2, ep2, _ = await prov.spawn(user_id)
    try:
        async with grpc.aio.insecure_channel(ep2) as ch:
            resp = await sandbox_pb2_grpc.SandboxStub(ch).ExecTool(
                sandbox_pb2.ExecToolRequest(
                    call_id="c2",
                    tool_name="read_file",
                    arguments_json='{"path": "keep.txt"}',
                    work_subdir="s1",
                )
            )
        assert resp.content == "v"
    finally:
        await prov.stop(sid2)


async def test_stop_unknown_is_noop(tmp_path):
    prov = InProcessProvisioner(base_root=tmp_path)
    await prov.stop(uuid.uuid4())  # should not raise


async def test_stop_all_clears_and_is_idempotent(tmp_path):
    # stop_all 必须停掉所有已起的 sandbox 服务并清空登记;否则泄漏的 aio server 会在
    # 解释器退出时被 GC 终结(Event loop is closed)挂死整进程。
    prov = InProcessProvisioner(base_root=tmp_path)
    await prov.spawn(uuid.uuid4())
    await prov.spawn(uuid.uuid4())
    await prov.stop_all()
    assert prov._servers == {}
    await prov.stop_all()  # idempotent, no raise
