import json

from agent_cloud_sandbox.tools import _MAX_OUTPUT, run_tool


def test_write_then_read(tmp_path):
    content, err = run_tool(tmp_path, "s1", "write_file", '{"path": "a.txt", "content": "hello"}')
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


def test_bash_output_capped(tmp_path):
    # Output far larger than the cap must be truncated so it can't blow past
    # gRPC's 4MB message limit (RESOURCE_EXHAUSTED). #1
    content, err = run_tool(
        tmp_path, "s1", "bash", '{"command": "python3 -c \\"print(\'x\'*200000)\\""}'
    )
    assert err is False
    assert len(content) <= _MAX_OUTPUT + 64
    assert content.endswith("...[truncated]")


def test_bash_success_returns_stdout_only(tmp_path):
    # On success only stdout is returned; gRPC fork-handler noise lands on stderr
    # and must not contaminate the result. #3
    content, err = run_tool(tmp_path, "s1", "bash", '{"command": "echo out; echo err 1>&2"}')
    assert err is False
    assert content == "out\n"


def test_bash_nonzero_includes_stderr(tmp_path):
    # On failure stderr is still surfaced (in the error message) so the model can debug. #3
    content, err = run_tool(
        tmp_path, "s1", "bash", '{"command": "echo boom 1>&2; exit 3"}'
    )
    assert err is True
    assert "boom" in content


def test_bash_failure_strips_grpc_fork_noise(tmp_path):
    # gRPC fork-handler noise on stderr must be stripped from the failure message,
    # while real stderr is kept. #3 (noise filter)
    noise = (
        "I0607 18:12:04.907837 50876146 ev_poll_posix.cc:593] "
        "FD from fork parent still in poll list: fd(32, generation: 1)"
    )
    cmd = f"echo '{noise}' 1>&2; echo real-error 1>&2; exit 1"
    content, err = run_tool(tmp_path, "s1", "bash", json.dumps({"command": cmd}))
    assert err is True
    assert "real-error" in content
    assert "ev_poll_posix" not in content
    assert "FD from fork parent" not in content


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
    content, err = run_tool(
        tmp_path, "s1", "write_file", '{"path": "../escape.txt", "content": "x"}'
    )
    assert err is True and "escapes working directory" in content
    assert not (tmp_path / "escape.txt").exists()


def test_absolute_path_rejected(tmp_path):
    _, err = run_tool(tmp_path, "s1", "read_file", '{"path": "/etc/hosts"}')
    assert err is True


def test_work_subdir_escape_rejected(tmp_path):
    # The sandbox owns per-user isolation (spec §11): work_subdir must not escape base. #4
    content, err = run_tool(
        tmp_path, "../evil", "write_file", '{"path": "a.txt", "content": "x"}'
    )
    assert err is True
    assert "invalid work_subdir" in content
    # nothing written outside base
    assert not (tmp_path.parent / "evil").exists()


def test_work_subdir_absolute_rejected(tmp_path):
    content, err = run_tool(
        tmp_path, "/etc", "write_file", '{"path": "a.txt", "content": "x"}'
    )
    assert err is True
    assert "invalid work_subdir" in content


def test_work_subdir_empty_rejected(tmp_path):
    # Empty subdir would land at the base root -> no per-user isolation. #4
    content, err = run_tool(tmp_path, "", "write_file", '{"path": "a.txt", "content": "x"}')
    assert err is True
    assert "invalid work_subdir" in content
    assert not (tmp_path / "a.txt").exists()


def test_os_error_does_not_leak_absolute_base_path(tmp_path):
    # OS errors must be relativized so the model never sees the host's absolute base. #6
    content, err = run_tool(tmp_path, "s1", "read_file", '{"path": "missing.txt"}')
    assert err is True
    assert str(tmp_path) not in content
    # resolved form too (macOS /var -> /private/var symlink)
    assert str(tmp_path.resolve()) not in content


def test_non_dict_arguments_rejected(tmp_path):
    # A JSON array is valid JSON but not a tool-args object. #7
    content, err = run_tool(tmp_path, "s1", "bash", "[]")
    assert err is True
    assert "must be a JSON object" in content


def test_symlink_escape_rejected(tmp_path):
    # Lock in good behavior: a symlink pointing outside the workdir must not be a
    # read escape hatch. bash creates the link, read_file must reject it.
    _, err = run_tool(tmp_path, "s1", "bash", '{"command": "ln -s /etc link"}')
    assert err is False
    content, err = run_tool(tmp_path, "s1", "read_file", '{"path": "link/hosts"}')
    assert err is True
    assert "escapes working directory" in content
