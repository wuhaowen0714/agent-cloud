from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from agent_cloud_common import ToolCall, ToolResult, ToolSpec


@dataclass
class Tool:
    spec: ToolSpec
    func: Callable[[Path, dict], str]  # 同步实现;executor 在线程里跑


class ToolExecutor(Protocol):
    def specs(self) -> list[ToolSpec]: ...
    async def execute(self, call: ToolCall) -> ToolResult: ...


class LocalToolExecutor:
    """在本地临时工作目录执行工具。是未来 gRPC 沙箱执行器的本地替身(同一接口)。"""

    def __init__(self, workdir: Path, tools: list[Tool]) -> None:
        self.workdir = Path(workdir)
        self._tools = {t.spec.name: t for t in tools}

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    async def execute(self, call: ToolCall) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(call_id=call.id, content=f"unknown tool: {call.name}", is_error=True)
        try:
            content = await asyncio.to_thread(tool.func, self.workdir, call.arguments)
            return ToolResult(call_id=call.id, content=content, is_error=False)
        except Exception as exc:  # 工具失败回填为错误结果,交回模型决定下一步
            return ToolResult(call_id=call.id, content=str(exc), is_error=True)


# ---- 内置工具实现 ----
def _bash(workdir: Path, args: dict) -> str:
    proc = subprocess.run(
        args["command"],
        shell=True,
        cwd=workdir,
        capture_output=True,
        text=True,
    )
    output = proc.stdout + proc.stderr
    if proc.returncode != 0:
        raise RuntimeError(f"exit {proc.returncode}: {output}")
    return output


def _write_file(workdir: Path, args: dict) -> str:
    target = workdir / args["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(args["content"])
    return f"wrote {args['path']}"


def _read_file(workdir: Path, args: dict) -> str:
    return (workdir / args["path"]).read_text()


def builtin_tools() -> list[Tool]:
    return [
        Tool(
            spec=ToolSpec(
                name="bash",
                description="Run a shell command in the working directory.",
                input_schema={
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            ),
            func=_bash,
        ),
        Tool(
            spec=ToolSpec(
                name="write_file",
                description="Write text to a file (relative to the working directory).",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["path", "content"],
                },
            ),
            func=_write_file,
        ),
        Tool(
            spec=ToolSpec(
                name="read_file",
                description="Read a file (relative to the working directory).",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            ),
            func=_read_file,
        ),
    ]
