from agent_cloud_worker.sandbox_executor import filtered_tool_specs


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
