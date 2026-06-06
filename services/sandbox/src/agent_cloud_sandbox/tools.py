from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path


def _resolve_within(workdir: Path, path: str) -> Path:
    candidate = (workdir / path).resolve()
    if not candidate.is_relative_to(workdir.resolve()):
        raise ValueError(f"path escapes working directory: {path}")
    return candidate


# bash 执行任意命令;进程/文件系统隔离由真实部署的沙箱(microVM/gVisor + cgroups,
# spec §11)负责,不是这段本地实现的职责。
def _bash(workdir: Path, args: dict) -> str:
    proc = subprocess.run(
        args["command"], shell=True, cwd=workdir, capture_output=True, text=True
    )
    output = proc.stdout + proc.stderr
    if proc.returncode != 0:
        raise RuntimeError(f"exit {proc.returncode}: {output}")
    return output


def _write_file(workdir: Path, args: dict) -> str:
    content = args["content"]  # 先取,缺失则在写盘前就报错
    target = _resolve_within(workdir, args["path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return f"wrote {args['path']}"


def _read_file(workdir: Path, args: dict) -> str:
    return _resolve_within(workdir, args["path"]).read_text()


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

    workdir = Path(base_workdir) / work_subdir
    workdir.mkdir(parents=True, exist_ok=True)

    func = _TOOLS.get(tool_name)
    if func is None:
        return (f"unknown tool: {tool_name}", True)
    try:
        return (func(workdir, args), False)
    except KeyError as exc:
        return (f"missing required argument: {exc.args[0]}", True)
    except Exception as exc:
        return (str(exc), True)
