from __future__ import annotations

from agent_cloud_common import ContextDocument, MemoryItem, SkillRef


def _escape_xml(s: str) -> str:
    # & 必须最先替换,否则会二次转义后续插入的实体;防止技能元数据破坏 <skill> XML 结构。
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _render_docs(documents: list[ContextDocument]) -> list[str]:
    # 用户级在前,agent 级在后;各自保持输入顺序
    ordered = [d for d in documents if d.scope == "user"] + [
        d for d in documents if d.scope != "user"
    ]
    return [f"# {d.type} ({d.scope})\n{d.content}" for d in ordered]


def _render_memory(memory: list[MemoryItem]) -> list[str]:
    if not memory:
        return []
    lines = ["# Memory"]
    for m in memory:
        lines.append(f"- ({m.scope}) {m.content}")
    return ["\n".join(lines)]


def _render_skills(skills: list[SkillRef]) -> list[str]:
    if not skills:
        return []
    lines = [
        "The following skills provide specialized instructions for specific tasks.",
        "Read a skill's file (location) when the task matches its description.",
        "<available_skills>",
    ]
    for s in skills:
        lines.append(
            f"  <skill><name>{_escape_xml(s.name)}</name>"
            f"<description>{_escape_xml(s.description)}</description>"
            f"<location>{_escape_xml(s.location)}</location></skill>"
        )
    lines.append("</available_skills>")
    return ["\n".join(lines)]


# 基础系统提示词:无论是否有用户级文档/记忆/技能都先注入,给模型最起码的环境认知
# (沙箱工作目录 + 相对路径约定)。否则空 system 会让模型幻觉 /workspace 之类不存在的
# 绝对路径(实测 DeepSeek 会 `cd /workspace/<id>` 然后失败)。
BASE_SYSTEM_PROMPT = """\
You are an autonomous AI agent running inside an isolated sandbox.

Working directory and files:
- You have a private working directory. The file tools (read_file, write_file) and the bash \
tool all operate inside this working directory.
- Always use relative paths (e.g. `notes.txt`, `src/app.py`, `python3 script.py`). Do not use \
absolute paths and do not assume any specific location such as `/workspace`, `/home`, or `/tmp` \
— they may not exist.
- Each bash call runs in a fresh shell that starts in the working directory. A `cd` affects only \
that single command and does not carry over to the next call, so run files directly (e.g. \
`python3 script.py`) rather than `cd`-ing first."""


def build_system_prompt(
    *,
    documents: list[ContextDocument],
    memory: list[MemoryItem],
    skills: list[SkillRef],
) -> str:
    """基础环境提示词 + 配置文档(用户级在前)+ 记忆 + 技能元数据,拼成分层 system 文本(spec §5.3)。"""
    sections = [
        BASE_SYSTEM_PROMPT,
        *_render_docs(documents),
        *_render_memory(memory),
        *_render_skills(skills),
    ]
    return "\n\n".join(sections)
