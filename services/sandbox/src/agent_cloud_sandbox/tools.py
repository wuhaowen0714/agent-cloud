from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

# 工具输出上限。bash 可能产出任意大的输出,超过 gRPC 默认 4MB 消息上限会导致
# RESOURCE_EXHAUSTED 崩溃,因此在沙箱侧先截断。
_MAX_OUTPUT = 100_000
_TRUNCATION_MARKER = "\n...[truncated]"


def _resolve_within(workdir: Path, path: str) -> Path:
    candidate = (workdir / path).resolve()
    if not candidate.is_relative_to(workdir.resolve()):
        raise ValueError(f"path escapes working directory: {path}")
    return candidate


def _truncate(output: str) -> str:
    if len(output) <= _MAX_OUTPUT:
        return output
    return output[:_MAX_OUTPUT] + _TRUNCATION_MARKER


# bash 执行任意命令;进程/文件系统隔离由真实部署的沙箱(microVM/gVisor + cgroups,
# spec §11)负责,不是这段本地实现的职责。
def _bash(workdir: Path, args: dict) -> str:
    proc = subprocess.run(args["command"], shell=True, cwd=workdir, capture_output=True, text=True)
    # 成功时只回 stdout:gRPC 的 fork/poll 噪声会落到子进程 stderr,排除 stderr 即可
    # 让正常输出保持干净(spec §3 噪声污染)。失败时把 stderr 一并带上便于排错。
    if proc.returncode != 0:
        raise RuntimeError(_truncate(f"exit {proc.returncode}: {proc.stdout}{proc.stderr}"))
    return _truncate(proc.stdout)


def _write_file(workdir: Path, args: dict) -> str:
    content = args["content"]  # 先取,缺失则在写盘前就报错
    target = _resolve_within(workdir, args["path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return f"wrote {args['path']}"


def _read_file(workdir: Path, args: dict) -> str:
    return _truncate(_resolve_within(workdir, args["path"]).read_text())


_TOOLS: dict[str, Callable[[Path, dict], str]] = {
    "bash": _bash,
    "write_file": _write_file,
    "read_file": _read_file,
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
