import asyncio

from agent_cloud_sandbox.pty_session import PtySession


async def _drain_until(pty: PtySession, needle: bytes, timeout: float = 5.0) -> bytes:
    buf = b""
    async with asyncio.timeout(timeout):
        while needle not in buf:
            chunk = await pty.read()
            if chunk == b"":
                break
            buf += chunk
    return buf


async def test_echo_roundtrip(tmp_path):
    pty = PtySession(tmp_path, rows=24, cols=80)
    await pty.start()
    try:
        await pty.write(b"echo hi-there\n")
        out = await _drain_until(pty, b"hi-there")
        assert b"hi-there" in out
    finally:
        await pty.close()


async def test_resize_no_raise(tmp_path):
    pty = PtySession(tmp_path, rows=24, cols=80)
    await pty.start()
    try:
        pty.resize(40, 100)  # 不抛
    finally:
        await pty.close()


async def test_exit_code(tmp_path):
    pty = PtySession(tmp_path, rows=24, cols=80)
    await pty.start()
    try:
        await pty.write(b"exit 0\n")
        code = await pty.wait()
        assert code == 0
    finally:
        await pty.close()


async def test_read_returns_eof_after_exit(tmp_path):
    # 子进程退出后 read() 最终返回 b"" 哨兵(供 server 收尾)
    pty = PtySession(tmp_path, rows=24, cols=80)
    await pty.start()
    try:
        await pty.write(b"exit 0\n")
        got_eof = False
        async with asyncio.timeout(5):
            while True:
                chunk = await pty.read()
                if chunk == b"":
                    got_eof = True
                    break
        assert got_eof
    finally:
        await pty.close()


async def test_close_is_idempotent(tmp_path):
    pty = PtySession(tmp_path, rows=24, cols=80)
    await pty.start()
    await pty.close()
    await pty.close()  # 再调不抛


async def test_history_persists_across_sessions(tmp_path):
    # 软状态:命令历史落 <workdir>/.home/.bash_history,跨会话累积。
    s1 = PtySession(tmp_path, rows=24, cols=80)
    await s1.start()
    await s1.write(b"echo persisted-marker\n")
    await _drain_until(s1, b"persisted-marker")
    await s1.write(b"exit\n")
    await s1.wait()
    await s1.close()
    hist = tmp_path / ".home" / ".bash_history"
    assert hist.exists()
    assert "persisted-marker" in hist.read_text()


async def test_cwd_persists_across_sessions(tmp_path):
    # 软状态:退出时记 cwd,下次启动自动 cd 回去。
    (tmp_path / "subdir").mkdir()
    s1 = PtySession(tmp_path, rows=24, cols=80)
    await s1.start()
    await s1.write(b"cd subdir\n")
    await s1.write(b"echo done\n")
    await _drain_until(s1, b"done")
    await s1.write(b"exit\n")
    await s1.wait()
    await s1.close()
    last_pwd = tmp_path / ".home" / ".last_pwd"
    assert last_pwd.exists()
    assert last_pwd.read_text().strip().endswith("subdir")
