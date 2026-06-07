import grpc
from agent_cloud_common import ToolCall
from agent_cloud_worker.sandbox_executor import SandboxToolExecutor, filtered_tool_specs


def test_empty_enabled_tools_exposes_all():
    assert {s.name for s in filtered_tool_specs([])} == {"bash", "write_file", "read_file"}


def test_filters_to_enabled_subset():
    assert [s.name for s in filtered_tool_specs(["read_file"])] == ["read_file"]


def test_unknown_enabled_tool_ignored():
    assert {s.name for s in filtered_tool_specs(["read_file", "nope"])} == {"read_file"}


def test_order_follows_builtin_not_request():
    # 过滤保持内置顺序,稳定可预期
    names = [s.name for s in filtered_tool_specs(["read_file", "bash"])]
    assert names == ["bash", "read_file"]


async def test_execute_rejects_disabled_tool():
    # enabled_tools 在 worker(可信侧)强制:调用未启用的工具直接回错误结果,
    # 根本不下发给沙箱(guard 在 stub 调用之前短路,无需真沙箱)。
    async with grpc.aio.insecure_channel("localhost:1") as ch:
        executor = SandboxToolExecutor(ch, "sessions/x", ["read_file"])
        res = await executor.execute(ToolCall(id="c1", name="bash", arguments={"command": "ls"}))
    assert res.is_error
    assert "not enabled" in res.content
