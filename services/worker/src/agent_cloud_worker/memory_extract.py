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


def _parse(text: str, current: str) -> tuple[str, bool]:
    s = text.strip()
    if s.startswith("```"):  # 容错:去掉 ```json ... ``` 围栏
        parts = s.split("```")
        s = parts[1] if len(parts) >= 2 else s
        if s.lstrip().startswith("json"):
            s = s.lstrip()[4:]
        s = s.strip()
    try:
        obj = json.loads(s)
        mem = str(obj["memory"])
        changed = bool(obj["changed"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return current, False  # 解析失败 = 不动现有块
    return (mem, True) if changed else (current, False)


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
    mem, changed = _parse(result.message.text, current)
    return mem, changed, result.usage
