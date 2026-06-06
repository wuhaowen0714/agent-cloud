from __future__ import annotations

from agent_cloud_common.types import ToolSpec


def builtin_tool_specs() -> list[ToolSpec]:
    """内置工具的对外规格(实现位于 sandbox 服务)。"""
    return [
        ToolSpec(
            name="bash",
            description="Run a shell command in the working directory.",
            input_schema={"type": "object",
                          "properties": {"command": {"type": "string"}},
                          "required": ["command"]},
        ),
        ToolSpec(
            name="write_file",
            description="Write text to a file (relative to the working directory).",
            input_schema={"type": "object",
                          "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                          "required": ["path", "content"]},
        ),
        ToolSpec(
            name="read_file",
            description="Read a file (relative to the working directory).",
            input_schema={"type": "object",
                          "properties": {"path": {"type": "string"}},
                          "required": ["path"]},
        ),
    ]
