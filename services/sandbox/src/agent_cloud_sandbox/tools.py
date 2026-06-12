from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from agent_cloud_common import apply_edits

# 工具输出上限。bash 可能产出任意大的输出,超过 gRPC 默认 4MB 消息上限会导致
# RESOURCE_EXHAUSTED 崩溃,因此在沙箱侧先截断。
_MAX_OUTPUT = 100_000
_TRUNCATION_MARKER = "\n...[truncated]"

# bash 单命令执行上限(秒,env 可配)。超时杀整个进程组并返回错误,防止不退出的命令
# (起服务、sleep、`cmd &` 后台进程持有管道)永久卡死整个沙箱(线上事故根因)。
_BASH_TIMEOUT_SECONDS = float(os.environ.get("AGENT_CLOUD_SANDBOX_BASH_TIMEOUT", "300"))


def _resolve_within(workdir: Path, path: str) -> Path:
    candidate = (workdir / path).resolve()
    if not candidate.is_relative_to(workdir.resolve()):
        raise ValueError(f"path escapes working directory: {path}")
    return candidate


def _truncate(output: str) -> str:
    if len(output) <= _MAX_OUTPUT:
        return output
    return output[:_MAX_OUTPUT] + _TRUNCATION_MARKER


def _clean_stderr(stderr: str) -> str:
    # gRPC C-core 在 fork 子进程(shell=True)时会把 "FD from fork parent still in poll list"
    # 之类噪声打到 stderr(ev_poll_posix.cc)。命令失败时我们会带上 stderr 便于排错,但这些
    # 噪声会污染错误信息,故按行剔除(spec §3 噪声污染)。
    lines = [
        ln
        for ln in stderr.splitlines()
        if "ev_poll_posix" not in ln and "FD from fork parent" not in ln
    ]
    return "\n".join(lines)


# bash 执行任意命令;进程/文件系统隔离由真实部署的沙箱(microVM/gVisor + cgroups,
# spec §11)负责,不是这段本地实现的职责。
def _bash(workdir: Path, args: dict) -> str:
    # start_new_session:命令跑在独立进程组(setsid),便于超时/超量时 killpg 杀整组——否则
    # `cmd &` 起的后台进程残留、持有 stdout 管道,读取永远等不到 EOF(经典 background-job hang,
    # 线上卡死整个沙箱的根因)。stdin=DEVNULL:读 stdin 的命令立刻拿到 EOF,不挂起等输入。
    proc = subprocess.Popen(
        args["command"],
        shell=True,
        cwd=workdir,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )

    def _kill_group() -> None:
        # 杀整个进程组(SIGKILL),含 shell 起的后台子进程。用 proc.pid 作 pgid(start_new_session
        # 使 proc 成组长,pgid == pid)——不调 os.getpgid:wait() 可能已 reap 退出的 shell,getpgid
        # 会 ProcessLookupError 被吞 → 后台漏杀。组内只要还有进程,pgid 就有效,killpg 能杀到。
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)

    timed_out = False
    capped = False

    def _read_capped(pipe, sink: list[str]) -> None:
        # 有界读:累计到 _MAX_OUTPUT 即停止累积并立刻 killpg(别等总超时),其后继续 read 但丢弃
        # (drain,避免写端被管道背压卡住)。防止海量输出(yes / 死循环 echo / cat /dev/urandom)
        # 把全部输出缓进内存 → 容器 OOM 被杀(communicate 无界缓冲,事后 _truncate 救不了:内存
        # 早爆了)。这是线上事故的另一条复活路径(512m 容器秒级 exit 137)。
        nonlocal capped
        total = 0
        try:
            while True:
                chunk = pipe.read(8192)
                if not chunk:
                    break
                if total < _MAX_OUTPUT:
                    sink.append(chunk)
                    total += len(chunk)
                    if total >= _MAX_OUTPUT:
                        capped = True
                        _kill_group()
        finally:
            with contextlib.suppress(Exception):
                pipe.close()

    out_parts: list[str] = []
    err_parts: list[str] = []
    t_out = threading.Thread(target=_read_capped, args=(proc.stdout, out_parts), daemon=True)
    t_err = threading.Thread(target=_read_capped, args=(proc.stderr, err_parts), daemon=True)
    t_out.start()
    t_err.start()

    def _on_timeout() -> None:
        nonlocal timed_out
        timed_out = True
        _kill_group()

    timer = threading.Timer(_BASH_TIMEOUT_SECONDS, _on_timeout)
    timer.start()
    try:
        # join 读线程 = 等到 stdout+stderr 双双 EOF,即所有持管道的进程(含 `cmd &` 后台)都已
        # 结束。后台 hang 时由 timer killpg(或超量 _kill_group)让 EOF 到来,join 才解除——故
        # 不能在 proc.wait() 后就 cancel timer:shell 退出 ≠ 后台进程退出。
        t_out.join()
        t_err.join()
        proc.wait()
    finally:
        timer.cancel()

    stdout = "".join(out_parts)
    stderr = _clean_stderr("".join(err_parts))
    if timed_out:
        raise RuntimeError(
            _truncate(
                f"command timed out after {_BASH_TIMEOUT_SECONDS:.0f}s and was killed "
                f"(whole process group). A long-running server/daemon must be detached so it "
                f"won't hold the pipe: `nohup <cmd> >/dev/null 2>&1 &`. Tune the limit via "
                f"AGENT_CLOUD_SANDBOX_BASH_TIMEOUT. Partial output: {stdout}{stderr}"
            )
        )
    # 输出超量:已截断 + 主动杀(防继续狂吐撑爆内存)。当成功结果返回(带截断标记),不报 exit
    # error——returncode 此时是被我们 SIGKILL 的 -9,但那是主动截断、不是命令失败。
    if capped:
        return _truncate(stdout)
    # 成功时只回 stdout:gRPC 的 fork/poll 噪声落在子进程 stderr,排除即可保持正常输出干净
    # (spec §3 噪声污染)。失败时把 stderr 一并带上便于排错。
    if proc.returncode != 0:
        raise RuntimeError(_truncate(f"exit {proc.returncode}: {stdout}{stderr}"))
    return _truncate(stdout)


def _write_file(workdir: Path, args: dict) -> str:
    content = args["content"]  # 先取,缺失则在写盘前就报错
    target = _resolve_within(workdir, args["path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return f"wrote {args['path']}"


def _read_file(workdir: Path, args: dict) -> str:
    return _truncate(_resolve_within(workdir, args["path"]).read_text())


def _edit(workdir: Path, args: dict) -> str:
    # 多段精确替换;apply_edits 失败抛 ValueError(可操作错误)→ run_tool 转成 is_error 交回模型。
    target = _resolve_within(workdir, args["path"])
    content = target.read_text()
    new_content = apply_edits(content, args["edits"])
    if new_content != content:
        target.write_text(new_content)
    return f"edited {args['path']}"


_TOOLS: dict[str, Callable[[Path, dict], str]] = {
    "bash": _bash,
    "write_file": _write_file,
    "read_file": _read_file,
    "edit": _edit,
}


def run_tool(
    base_workdir: Path, work_subdir: str, tool_name: str, arguments_json: str
) -> tuple[str, bool]:
    """执行一次工具调用,返回 (content, is_error)。"""
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError as exc:
        return (f"invalid arguments_json: {exc}", True)
    if not isinstance(args, dict):
        return ("arguments_json must be a JSON object", True)

    base = Path(base_workdir).resolve()
    # 沙箱负责 per-user 隔离(spec §11):work_subdir 不能用 .. 逃逸出 base,也不能是
    # 绝对路径或空(空会落到 base 根目录,等于无隔离)。
    if not work_subdir:
        return (f"invalid work_subdir: {work_subdir}", True)
    try:
        workdir = _resolve_within(base, work_subdir)
    except ValueError:
        return (f"invalid work_subdir: {work_subdir}", True)
    workdir.mkdir(parents=True, exist_ok=True)

    func = _TOOLS.get(tool_name)
    if func is None:
        return (f"unknown tool: {tool_name}", True)
    try:
        return (func(workdir, args), False)
    except KeyError as exc:
        return (f"missing required argument: {exc.args[0]}", True)
    except Exception as exc:
        # 不向模型泄露宿主绝对路径:把 base 前缀替换掉,只留 workdir 相对路径(spec §6)。
        return (str(exc).replace(str(base), "").replace(str(base_workdir), ""), True)


def run_write_binary(
    base_workdir: Path, work_subdir: str, path: str, content: bytes
) -> tuple[str, bool]:
    """把二进制字节落进工作区(worker 原生工具如图片生成专用)。返回 (相对路径 or 错误, is_error)。

    与 run_tool 同款围栏:work_subdir 非空且不逃逸 base;path 不逃逸 work_subdir。直接 write_bytes,
    落地即原始文件(不像 write_file 走 write_text 会损坏二进制 + 让 /files/raw 的 MIME 探测失效)。
    """
    base = Path(base_workdir).resolve()
    if not work_subdir:
        return (f"invalid work_subdir: {work_subdir}", True)
    try:
        workdir = _resolve_within(base, work_subdir)
    except ValueError:
        return (f"invalid work_subdir: {work_subdir}", True)
    if not path:
        return ("path is required", True)
    try:
        target = _resolve_within(workdir, path)
    except ValueError:
        return (f"path escapes working directory: {path}", True)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    except Exception as exc:
        # 同 run_tool:不泄露宿主绝对路径。
        return (str(exc).replace(str(base), "").replace(str(base_workdir), ""), True)
    return (path, False)
