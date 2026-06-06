from agent_cloud_sandbox.tools import run_tool


def test_write_then_read(tmp_path):
    content, err = run_tool(tmp_path, "s1", "write_file",
                            '{"path": "a.txt", "content": "hello"}')
    assert err is False
    content, err = run_tool(tmp_path, "s1", "read_file", '{"path": "a.txt"}')
    assert err is False and content == "hello"
    # 写到了 base/work_subdir 下
    assert (tmp_path / "s1" / "a.txt").read_text() == "hello"


def test_bash_runs_in_workdir(tmp_path):
    content, err = run_tool(tmp_path, "s1", "bash", '{"command": "echo hi"}')
    assert err is False and "hi" in content


def test_bash_nonzero_is_error(tmp_path):
    _, err = run_tool(tmp_path, "s1", "bash", '{"command": "exit 7"}')
    assert err is True


def test_unknown_tool(tmp_path):
    content, err = run_tool(tmp_path, "s1", "nope", "{}")
    assert err is True and "unknown tool" in content.lower()


def test_missing_argument_friendly(tmp_path):
    content, err = run_tool(tmp_path, "s1", "write_file", '{"path": "a.txt"}')
    assert err is True and "missing required argument" in content


def test_invalid_json(tmp_path):
    content, err = run_tool(tmp_path, "s1", "bash", "{not json")
    assert err is True and "invalid arguments_json" in content


def test_path_traversal_rejected(tmp_path):
    content, err = run_tool(tmp_path, "s1", "write_file",
                            '{"path": "../escape.txt", "content": "x"}')
    assert err is True and "escapes working directory" in content
    assert not (tmp_path / "escape.txt").exists()


def test_absolute_path_rejected(tmp_path):
    _, err = run_tool(tmp_path, "s1", "read_file", '{"path": "/etc/hosts"}')
    assert err is True
