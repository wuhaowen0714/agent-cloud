from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import signal
import struct
import sys
import termios
from pathlib import Path

# 启动器:让子 bash 把它的 stdin(PTY slave)设为 controlling tty,使 job control
# (Ctrl-C 只作用于前台进程组、vim 等全屏 TUI 正常)生效。为何走 `python -c` 而非
# preexec_fn:在 uvicorn+grpc 多线程进程里 fork 后跑 Python(preexec_fn)会因子进程
# 运行时状态损坏而崩。这里 start_new_session 由 C 层做 setsid(安全),随后 exec 出一个
# 干净的单线程 python(无多线程包袱)在 exec bash 前做 TIOCSCTTY——支持的平台(Linux)
# 绑定可靠,不支持的(macOS)容错降级。argv 透传给 bash(`-i` + 可选 rcfile)。
_BASH_LAUNCHER = (
    "import os,sys,fcntl,termios\n"
    "try:\n"
    "    fcntl.ioctl(0, termios.TIOCSCTTY, 0)\n"
    "except OSError:\n"
    "    pass\n"
    "os.execvp('bash', ['bash', *sys.argv[1:]])\n"
)


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

    @staticmethod
    def _render_rc(home: str) -> str:
        # 软状态持久(spec):历史落 <home>/.bash_history(跨会话累积),每个提示符把 cwd
        # 写 <home>/.last_pwd、启动 cd 回去。用绝对路径(cd 后相对会变)。再 source 用户
        # 自定义 <home>/.bashrc(若有)。<home> 在持久卷下,点目录在文件抽屉里隐藏(#31)。
        return (
            f'export HISTFILE="{home}/.bash_history"\n'
            "export HISTSIZE=5000 HISTFILESIZE=20000\n"
            "shopt -s histappend 2>/dev/null\n"
            f"PROMPT_COMMAND='history -a; pwd > \"{home}/.last_pwd\"'\n"
            f'__lp="$(cat "{home}/.last_pwd" 2>/dev/null)"; [ -d "$__lp" ] && cd "$__lp"\n'
            f'[ -f "{home}/.bashrc" ] && . "{home}/.bashrc"\n'
        )

    async def start(self) -> None:
        self._workdir.mkdir(parents=True, exist_ok=True)
        home = self._workdir / ".home"
        home.mkdir(parents=True, exist_ok=True)
        rc = home / ".term_rcfile"
        rc.write_text(self._render_rc(str(home)))
        master, slave = pty.openpty()
        self._set_winsize(master, self._rows, self._cols)
        env = self._env if self._env is not None else dict(os.environ)
        env.setdefault("TERM", "xterm-256color")
        self._proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            _BASH_LAUNCHER,
            "--rcfile",
            str(rc),
            "-i",
            *self._extra_bash_args,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=str(self._workdir),
            env=env,
            # start_new_session:CPython 在 fork 后 C 层(_posixsubprocess)做 setsid,多线程
            # 安全。controlling tty 的绑定由上面 _BASH_LAUNCHER 在 exec 后的干净进程里完成。
            start_new_session=True,
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
