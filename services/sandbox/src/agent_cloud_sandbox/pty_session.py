from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import signal
import struct
import termios
from pathlib import Path


def _make_controlling_tty(slave: int):
    # 子进程 fork 后:slave 成为 controlling tty,让 job control(Ctrl-C 作用于前台
    # 进程组而非整个沙箱服务)正常工作。start_new_session 已 setsid,这里补 TIOCSCTTY。
    def _pre() -> None:
        fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

    return _pre


class PtySession:
    """一个 PTY + 交互式 bash 子进程。

    master fd 设非阻塞 + loop.add_reader,输出推进 asyncio.Queue,read() 异步消费。
    子进程退出 → master EOF → 入队 b"" 哨兵(server 据此发 exit_code 收尾)。
    """

    def __init__(
        self,
        workdir: Path,
        rows: int = 24,
        cols: int = 80,
        env: dict[str, str] | None = None,
        extra_bash_args: list[str] | None = None,
    ) -> None:
        self._workdir = Path(workdir)
        self._rows = rows or 24
        self._cols = cols or 80
        self._env = env
        self._extra_bash_args = extra_bash_args or []
        self._master: int | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._closed = False

    async def start(self) -> None:
        self._workdir.mkdir(parents=True, exist_ok=True)
        master, slave = pty.openpty()
        self._set_winsize(master, self._rows, self._cols)
        env = self._env if self._env is not None else dict(os.environ)
        env.setdefault("TERM", "xterm-256color")
        self._proc = await asyncio.create_subprocess_exec(
            "bash",
            "-i",
            *self._extra_bash_args,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=str(self._workdir),
            env=env,
            start_new_session=True,  # setsid:独立进程组(Ctrl-C 只杀前台组,不杀沙箱服务)
            preexec_fn=_make_controlling_tty(slave),
        )
        os.close(slave)  # 父进程不持有 slave;仅子进程经 stdio 持有
        os.set_blocking(master, False)
        self._master = master
        asyncio.get_running_loop().add_reader(master, self._on_readable)

    def _on_readable(self) -> None:
        assert self._master is not None
        try:
            data = os.read(self._master, 65536)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            data = b""  # PTY 关闭(子进程退出/master 失效)
        if data:
            self._queue.put_nowait(data)
        else:
            try:
                asyncio.get_running_loop().remove_reader(self._master)
            except (ValueError, OSError):
                pass
            self._queue.put_nowait(b"")  # EOF 哨兵

    async def read(self) -> bytes:
        """下一段 PTY 输出;子进程退出后返回 b""(哨兵)。"""
        return await self._queue.get()

    async def write(self, data: bytes) -> None:
        if self._master is not None and not self._closed:
            try:
                os.write(self._master, data)
            except OSError:
                pass  # 子进程已退出,写入丢弃

    def resize(self, rows: int, cols: int) -> None:
        if self._master is not None:
            self._set_winsize(self._master, rows or 24, cols or 80)

    @staticmethod
    def _set_winsize(fd: int, rows: int, cols: int) -> None:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    async def wait(self) -> int:
        assert self._proc is not None
        return await self._proc.wait()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._master is not None:
            try:
                asyncio.get_running_loop().remove_reader(self._master)
            except (ValueError, OSError):
                pass
        if self._proc is not None and self._proc.returncode is None:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                async with asyncio.timeout(2):
                    await self._proc.wait()
            except TimeoutError:
                pass
        if self._master is not None:
            try:
                os.close(self._master)
            except OSError:
                pass
            self._master = None
