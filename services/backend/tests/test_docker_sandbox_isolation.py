import asyncio
import json
import uuid

import grpc
import pytest
from agent_cloud.v1 import sandbox_pb2, sandbox_pb2_grpc
from agent_cloud_backend.sandbox.docker_provisioner import DockerProvisioner

pytestmark = pytest.mark.docker


async def _exec(endpoint: str, token: str, tool: str, args: dict, work_subdir: str = "."):
    """连沙箱执行一次工具(带鉴权 token,模拟 worker);容器 boot 可能慢,简单重试。
    返回 (content, is_error)。"""
    md = (("x-sandbox-token", token),) if token else ()
    async with grpc.aio.insecure_channel(endpoint) as ch:
        stub = sandbox_pb2_grpc.SandboxStub(ch)
        last: Exception | None = None
        for _ in range(20):
            try:
                resp = await stub.ExecTool(
                    sandbox_pb2.ExecToolRequest(
                        call_id="t",
                        tool_name=tool,
                        arguments_json=json.dumps(args),
                        work_subdir=work_subdir,
                    ),
                    metadata=md,
                )
                return resp.content, resp.is_error
            except grpc.aio.AioRpcError as e:
                last = e
                await asyncio.sleep(0.5)
        raise last  # type: ignore[misc]


async def test_user_b_cannot_read_user_a_files(tmp_path):
    prov = DockerProvisioner(
        host_root=str(tmp_path), image="agent-cloud-sandbox:latest", network_mode="publish"
    )
    a, b = uuid.uuid4(), uuid.uuid4()
    sid_a, ep_a, tok_a = await prov.spawn(a)
    sid_b, ep_b, tok_b = await prov.spawn(b)
    try:
        # A 写一个秘密文件
        _, err = await _exec(
            ep_a, tok_a, "write_file", {"path": "secret.txt", "content": "TOP-SECRET"}
        )
        assert err is False
        # 宿主上确认它在 A 的卷里
        assert (tmp_path / str(a) / "workspace" / "secret.txt").read_text() == "TOP-SECRET"

        # B 用 bash 按宿主绝对路径读 A 的文件 → 容器里没这个路径 → 读不到
        host_path_of_a = str(tmp_path / str(a) / "workspace" / "secret.txt")
        content, _ = await _exec(ep_b, tok_b, "bash", {"command": f"cat {host_path_of_a}"})
        assert "TOP-SECRET" not in content  # 越权失败

        # B 列根 / workspace 也看不到别的用户目录
        content, _ = await _exec(
            ep_b, tok_b, "bash", {"command": "ls / ; echo ---- ; ls /workspace"}
        )
        assert str(a) not in content
    finally:
        await prov.stop(sid_a)
        await prov.stop(sid_b)


async def test_sandbox_has_cli_toolchain(tmp_path):
    # 镜像自带 curl/wget/git/jq:agent 的 bash 工具开箱可用(不需运行期 apt)
    prov = DockerProvisioner(
        host_root=str(tmp_path), image="agent-cloud-sandbox:latest", network_mode="publish"
    )
    sid, ep, tok = await prov.spawn(uuid.uuid4())
    try:
        for tool in ("curl", "wget", "git", "jq"):
            out, err = await _exec(ep, tok, "bash", {"command": f"{tool} --version"})
            assert err is False, f"{tool} --version errored: {out}"
            assert out.strip(), f"{tool} --version produced no output"
    finally:
        await prov.stop(sid)


async def test_sandbox_git_works_out_of_the_box(tmp_path):
    # git 免身份/ownership 配置:bind-mount 的 /workspace 不报 dubious ownership,
    # 首次 commit 不报 "tell me who you are"(system 级 safe.directory + 兜底身份)
    prov = DockerProvisioner(
        host_root=str(tmp_path), image="agent-cloud-sandbox:latest", network_mode="publish"
    )
    sid, ep, tok = await prov.spawn(uuid.uuid4())
    try:
        cmd = (
            "git init -q && echo hi > f.txt && git add f.txt "
            "&& git commit -q -m init && git log --oneline"
        )
        out, err = await _exec(ep, tok, "bash", {"command": cmd})
        assert err is False, f"git flow errored: {out}"
        assert "init" in out
    finally:
        await prov.stop(sid)


async def test_pip_dependency_survives_container_respawn(tmp_path):
    prov = DockerProvisioner(
        host_root=str(tmp_path), image="agent-cloud-sandbox:latest", network_mode="publish"
    )
    u = uuid.uuid4()
    sid1, ep1, tok1 = await prov.spawn(u)
    try:
        # PIP_USER=1 → 装进 /workspace/.home/.local(在卷里)
        cmd = "pip install --quiet six && python -c 'import six; print(six.__version__)'"
        out, err = await _exec(ep1, tok1, "bash", {"command": cmd})
        assert err is False and out.strip()
    finally:
        await prov.stop(sid1)  # 冷重建:杀掉容器

    # 同一用户重新 spawn(挂回同卷)→ six 仍能 import
    sid2, ep2, tok2 = await prov.spawn(u)
    try:
        out, err = await _exec(
            ep2, tok2, "bash", {"command": "python -c 'import six; print(six.__version__)'"}
        )
        assert err is False and out.strip()  # 依赖跨重建保留
    finally:
        await prov.stop(sid2)


async def test_sandbox_rejects_missing_token(tmp_path):
    # 纵深防御:有 token 的沙箱,不带 token 直连 ExecTool → UNAUTHENTICATED
    prov = DockerProvisioner(
        host_root=str(tmp_path), image="agent-cloud-sandbox:latest", network_mode="publish"
    )
    sid, ep, tok = await prov.spawn(uuid.uuid4())
    try:
        assert tok  # docker provisioner 必生成 token
        # 先用正确 token 确认沙箱已就绪
        _, err = await _exec(ep, tok, "bash", {"command": "echo ok"})
        assert err is False
        # 不带 token → 拒
        with pytest.raises(grpc.aio.AioRpcError) as ei:
            await _exec(ep, "", "bash", {"command": "echo pwned"})
        assert ei.value.code() == grpc.StatusCode.UNAUTHENTICATED
        # 错 token → 拒
        with pytest.raises(grpc.aio.AioRpcError) as ei2:
            await _exec(ep, "wrong-token", "bash", {"command": "echo pwned"})
        assert ei2.value.code() == grpc.StatusCode.UNAUTHENTICATED
    finally:
        await prov.stop(sid)
