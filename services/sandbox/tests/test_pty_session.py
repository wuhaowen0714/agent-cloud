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
