import json
import time

from agent_cloud_sandbox.tools import (
    _MAX_OUTPUT,
    _TRUNCATION_MARKER,
    run_read_binary,
    run_tool,
    run_write_binary,
)


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
    content, err = run_tool(tmp_path, "s1", "bash", '{"command": "echo boom 1>&2; exit 3"}')
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


def test_bash_timeout_kills_runaway_command(monkeypatch, tmp_path):
    # 不退出的命令(sleep)→ 超时杀进程组、转 is_error。时间断言防"假绿":必须真被杀(~1s),
    # 而非等 sleep 自己结束(v2 回归就是杀不掉、卡满 30s 但 err/"timed out" 断言照样过)。
    from agent_cloud_sandbox import tools

    monkeypatch.setattr(tools, "_BASH_TIMEOUT_SECONDS", 1.0)
    t0 = time.monotonic()
    content, err = run_tool(tmp_path, "s1", "bash", json.dumps({"command": "sleep 30"}))
    elapsed = time.monotonic() - t0
    assert err is True
    assert "timed out" in content
    assert elapsed < 5, f"应被超时杀掉(~1s),实际 {elapsed:.1f}s——kill 没生效"


def test_bash_timeout_kills_background_pipe_holder(monkeypatch, tmp_path):
    # 经典 background-job hang:后台进程持有 stdout 管道,无 timeout 永久卡(沙箱卡死);
    # timeout + killpg 整组超时杀。时间断言确保真杀掉(~1s)而非卡到 sleep 结束。
    from agent_cloud_sandbox import tools

    monkeypatch.setattr(tools, "_BASH_TIMEOUT_SECONDS", 1.0)
    t0 = time.monotonic()
    content, err = run_tool(
        tmp_path, "s1", "bash", json.dumps({"command": "sleep 30 & echo started"})
    )
    elapsed = time.monotonic() - t0
    assert err is True
    assert "timed out" in content
    assert elapsed < 5, f"后台进程应被 killpg 杀(~1s),实际 {elapsed:.1f}s"


def test_bash_caps_runaway_output(tmp_path):
    # 海量输出(yes 无限)必须有界读 + 超量主动杀:不能全缓进内存(512m 容器秒级 OOM),也不能
    # 卡满超时。截断到 _MAX_OUTPUT 且快速返回(C2 事故复活路径)。
    t0 = time.monotonic()
    content, err = run_tool(tmp_path, "s1", "bash", json.dumps({"command": "yes"}))
    elapsed = time.monotonic() - t0
    assert len(content) <= _MAX_OUTPUT + len(_TRUNCATION_MARKER) + 16
    assert elapsed < 15, f"超量应主动杀、快速返回,实际 {elapsed:.1f}s"


def test_bash_stdin_is_devnull(tmp_path):
    # 读 stdin 的命令(cat 无参)在 DEVNULL 下立即拿到 EOF 返回,而非永久挂起等输入。
    t0 = time.monotonic()
    content, err = run_tool(tmp_path, "s1", "bash", json.dumps({"command": "cat"}))
    elapsed = time.monotonic() - t0
    assert err is False
    assert elapsed < 5


def test_edit_replaces_text(tmp_path):
    run_tool(tmp_path, "s1", "write_file", '{"path": "a.py", "content": "x = 1\\n"}')
    _, err = run_tool(
        tmp_path,
        "s1",
        "edit",
        json.dumps({"path": "a.py", "edits": [{"old_text": "x = 1", "new_text": "x = 2"}]}),
    )
    assert err is False
    assert (tmp_path / "s1" / "a.py").read_text() == "x = 2\n"


def test_edit_not_found_is_error(tmp_path):
    run_tool(tmp_path, "s1", "write_file", '{"path": "a.py", "content": "hello"}')
    content, err = run_tool(
        tmp_path,
        "s1",
        "edit",
        json.dumps({"path": "a.py", "edits": [{"old_text": "nope", "new_text": "x"}]}),
    )
    assert err is True and "not found" in content


def test_edit_ambiguous_is_error(tmp_path):
    run_tool(tmp_path, "s1", "write_file", '{"path": "a.py", "content": "z\\nz\\n"}')
    content, err = run_tool(
        tmp_path,
        "s1",
        "edit",
        json.dumps({"path": "a.py", "edits": [{"old_text": "z", "new_text": "q"}]}),
    )
    assert err is True and "unique" in content


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
    content, err = run_tool(tmp_path, "../evil", "write_file", '{"path": "a.txt", "content": "x"}')
    assert err is True
    assert "invalid work_subdir" in content
    # nothing written outside base
    assert not (tmp_path.parent / "evil").exists()


def test_work_subdir_absolute_rejected(tmp_path):
    content, err = run_tool(tmp_path, "/etc", "write_file", '{"path": "a.txt", "content": "x"}')
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


# --- run_write_binary:worker 原生工具(图片生成)的二进制落盘 ---

# 含非 UTF-8 字节的真二进制(PNG 魔数 + 0xFF/0x00):若误用 write_text 会 UnicodeEncodeError 或损坏。
_PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x01\xff\xfe\xfdbinary\x00data"


def test_write_binary_roundtrip(tmp_path):
    rel, err = run_write_binary(tmp_path, "s1", "media/picture/img.png", _PNG_BYTES)
    assert err is False
    assert rel == "media/picture/img.png"
    # 自动建嵌套父目录,落地是逐字节相同的原始二进制(非 base64/非文本)
    written = tmp_path / "s1" / "media" / "picture" / "img.png"
    assert written.read_bytes() == _PNG_BYTES


def test_write_binary_overwrites(tmp_path):
    run_write_binary(tmp_path, "s1", "a.png", b"old")
    rel, err = run_write_binary(tmp_path, "s1", "a.png", b"new-bytes")
    assert err is False
    assert (tmp_path / "s1" / "a.png").read_bytes() == b"new-bytes"


def test_write_binary_path_escape_rejected(tmp_path):
    rel, err = run_write_binary(tmp_path, "s1", "../evil.png", _PNG_BYTES)
    assert err is True
    assert "escapes working directory" in rel
    assert not (tmp_path / "evil.png").exists()


def test_write_binary_work_subdir_escape_rejected(tmp_path):
    rel, err = run_write_binary(tmp_path, "../evil", "img.png", _PNG_BYTES)
    assert err is True
    assert "invalid work_subdir" in rel
    assert not (tmp_path.parent / "evil").exists()


def test_write_binary_empty_work_subdir_rejected(tmp_path):
    rel, err = run_write_binary(tmp_path, "", "img.png", _PNG_BYTES)
    assert err is True
    assert "invalid work_subdir" in rel


def test_write_binary_empty_path_rejected(tmp_path):
    rel, err = run_write_binary(tmp_path, "s1", "", _PNG_BYTES)
    assert err is True
    assert "path is required" in rel


def test_write_binary_os_error_does_not_leak_base(tmp_path):
    # 父路径已是文件时写入失败 → OS 错误必须剥掉宿主绝对路径(同 run_tool §6)。
    run_write_binary(tmp_path, "s1", "blocker", b"x")  # 先占一个普通文件
    rel, err = run_write_binary(tmp_path, "s1", "blocker/child.png", _PNG_BYTES)
    assert err is True
    assert str(tmp_path) not in rel
    assert str(tmp_path.resolve()) not in rel


# --- run_read_binary:worker 原生工具(图片编辑)读工作区输入图 ---


def test_read_binary_roundtrip(tmp_path):
    # 先写一张图,再读回 —— 逐字节相同(真二进制透传)
    run_write_binary(tmp_path, "s1", "media/upload/in.png", _PNG_BYTES)
    data, err = run_read_binary(tmp_path, "s1", "media/upload/in.png")
    assert err == ""
    assert data == _PNG_BYTES


def test_read_binary_missing_file(tmp_path):
    data, err = run_read_binary(tmp_path, "s1", "media/upload/nope.png")
    assert data == b""
    assert "not a file" in err


def test_read_binary_path_escape_rejected(tmp_path):
    data, err = run_read_binary(tmp_path, "s1", "../../etc/hosts")
    assert data == b""
    assert "escapes working directory" in err


def test_read_binary_work_subdir_escape_rejected(tmp_path):
    data, err = run_read_binary(tmp_path, "../evil", "x.png")
    assert data == b""
    assert "invalid work_subdir" in err


def test_read_binary_empty_path_rejected(tmp_path):
    data, err = run_read_binary(tmp_path, "s1", "")
    assert data == b""
    assert "path is required" in err


def test_read_binary_dir_rejected(tmp_path):
    # 目录不是文件 → not a file(而不是 read_bytes 抛 IsADirectoryError)
    run_write_binary(tmp_path, "s1", "d/keep.txt", b"x")
    data, err = run_read_binary(tmp_path, "s1", "d")
    assert data == b""
    assert "not a file" in err


def test_read_binary_too_large_rejected(tmp_path, monkeypatch):
    import agent_cloud_sandbox.tools as t

    monkeypatch.setattr(t, "_MAX_READ_BYTES", 10)
    run_write_binary(tmp_path, "s1", "big.bin", b"x" * 50)
    data, err = run_read_binary(tmp_path, "s1", "big.bin")
    assert data == b""
    assert "too large" in err
