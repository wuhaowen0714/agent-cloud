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
        ToolSpec(
            name="edit",
            description=(
                "Edit a file in place by exact text replacement. Prefer this over write_file "
                "when changing part of a file (it won't drop the rest). `edits` is a list of "
                "{old_text, new_text}; each old_text must match exactly once — include enough "
                "surrounding context to be unique. Edits apply in order and are all-or-nothing."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "edits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_text": {"type": "string"},
                                "new_text": {"type": "string"},
                            },
                            "required": ["old_text", "new_text"],
                        },
                    },
                },
                "required": ["path", "edits"],
            },
        ),
    ]
