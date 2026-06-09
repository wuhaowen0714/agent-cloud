from __future__ import annotations

import json

from agent_cloud_common import CompletionRequest, Message, Role, Usage

from agent_cloud_worker.provider import Provider

# 记忆提炼(v1:仅 user 层)。给 LLM 当前块 + 最近对话,让它输出更新后的整块 + 是否有变。
_SYSTEM = """You maintain a compact MEMORY about a USER, reused across ALL of their agents.
Given the CURRENT memory and the RECENT conversation, return the UPDATED memory as markdown bullets.

Keep ONLY durable, cross-agent facts about the person: identity, role, timezone, language,
stable preferences (reply language, verbosity, coding style, tooling), long-term goals/projects.
Do NOT store: one-off or in-session details, low-confidence guesses, or facts specific to a single
agent's task. PRESERVE existing facts verbatim unless the conversation updates or contradicts them
(newer wins); remove outdated/contradicted facts; deduplicate.
Keep it concise, ideally under {soft} characters (this is a SOFT target — be terse and merge related
facts; never cut off mid-fact).

Output STRICT JSON only, no prose, no code fence:
{{"changed": <true|false>, "memory": "<the full updated memory>"}}
Set "changed" to false and echo the current memory if there is nothing durable to add or change."""


class MemoryParseError(Exception):
    """LLM 输出无法解析为 {changed, memory}。视为"提炼失败"(上层不推进水位线、下次重试),
    而非静默当作"无变化"—— 否则解析失败会被误当 no-op 推进水位线、永久丢掉本可记住的事实。"""


def _parse(text: str) -> tuple[str, bool]:
    """解析 {"changed": bool, "memory": str};失败抛 MemoryParseError。"""
    s = text.strip()
    if "```" in s:  # 去掉 ```json ... ``` 围栏(取首对围栏内内容)
        parts = s.split("```")
        if len(parts) >= 3:
            s = parts[1]
            if s.lstrip().lower().startswith("json"):
                s = s.lstrip()[4:]
            s = s.strip()
    start = s.find("{")  # 容忍前后多余说明文字:从第一个 { 起 raw_decode
    if start < 0:
        raise MemoryParseError("no JSON object in output")
    try:
        obj, _ = json.JSONDecoder().raw_decode(s[start:])
    except json.JSONDecodeError as e:
        raise MemoryParseError(str(e)) from e
    if (
        not isinstance(obj, dict)
        or not isinstance(obj.get("memory"), str)
        or not isinstance(obj.get("changed"), bool)
    ):
        raise MemoryParseError("missing or mistyped 'changed'/'memory'")
    return obj["memory"], obj["changed"]


def _render(messages: list[Message]) -> str:
    if not messages:
        return "(no new messages)"
    lines = []
    for m in messages:
        if not m.text:
            continue
        role = getattr(m.role, "value", m.role)
        lines.append(f"{role}: {m.text}")
    return "\n".join(lines) or "(no new messages)"


async def reconcile_user_memory(
    provider: Provider, *, current: str, messages: list[Message], soft_max_chars: int
) -> tuple[str, bool, Usage]:
    prompt = f"CURRENT MEMORY:\n{current or '(empty)'}\n\nRECENT CONVERSATION:\n{_render(messages)}"
    result = await provider.complete(
        CompletionRequest(
            system=_SYSTEM.format(soft=soft_max_chars),
            messages=[Message(role=Role.USER, text=prompt)],
            tools=[],
        )
    )
    # 解析失败 → 抛 MemoryParseError(handler 收敛为 INTERNAL)→ 后端不推进水位线、下次重试。
    mem, changed = _parse(result.message.text)
    return (mem if changed else current), changed, result.usage
