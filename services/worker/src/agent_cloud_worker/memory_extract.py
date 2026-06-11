from __future__ import annotations

import json

from agent_cloud_common import CompletionRequest, Message, Role, Usage

from agent_cloud_worker.provider import Provider

# 记忆提炼(v2:双块)。给 LLM 两块现值 + 最近对话,让它输出两块更新后的整块 + 各自是否有变。
# 分层判别与 remember 工具/注入渲染的措辞一致(三处互教);错层事实在这里被搬回正确的块。
_SYSTEM = """You maintain TWO compact MEMORY blocks for one AI agent that a user talks to.

USER memory — about the person; shared across ALL of their agents: identity, role, timezone,
language, stable preferences (reply language, verbosity, coding style, tooling), long-term
goals/projects. The agent itself is NOT the subject of this block.
AGENT memory — private to THIS agent: its given name/persona, conventions agreed with the user
for this role, durable domain notes for its job.
Discriminator: would the fact still hold for the user's OTHER agents? yes -> USER; no -> AGENT.

Given the CURRENT blocks and the RECENT conversation, return BOTH updated blocks as markdown
bullets. PRESERVE existing facts verbatim unless the conversation updates or contradicts them
(newer wins); remove outdated/contradicted facts; deduplicate; MOVE misfiled facts to their
correct block (e.g. the agent's own name found in USER memory belongs in AGENT memory, phrased
unambiguously). Do NOT store one-off or in-session details or low-confidence guesses. Keep each
block concise, ideally under {soft} characters (a SOFT target — be terse and merge related
facts; never cut off mid-fact).

Output STRICT JSON only, no prose, no code fence:
{{"user_changed": <true|false>, "user_memory": "<full updated user block>",
 "agent_changed": <true|false>, "agent_memory": "<full updated agent block>"}}
Set a *_changed to false and echo the current block if nothing durable changes for that block."""


class MemoryParseError(Exception):
    """LLM 输出无法解析为 {user_changed, user_memory, agent_changed, agent_memory}。
    视为"提炼失败"(上层不推进水位线、下次重试),而非静默当作"无变化"——
    否则解析失败会被误当 no-op 推进水位线、永久丢掉本可记住的事实。"""


def _parse(text: str) -> tuple[str, bool, str, bool]:
    """解析双块 JSON;缺键/错型/旧式单块输出一律抛 MemoryParseError。"""
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
    if not isinstance(obj, dict):
        raise MemoryParseError("output is not a JSON object")
    for key, typ in (
        ("user_changed", bool),
        ("user_memory", str),
        ("agent_changed", bool),
        ("agent_memory", str),
    ):
        if not isinstance(obj.get(key), typ):
            raise MemoryParseError(f"missing or mistyped '{key}'")
    return obj["user_memory"], obj["user_changed"], obj["agent_memory"], obj["agent_changed"]


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


async def reconcile_memory(
    provider: Provider,
    *,
    user_current: str,
    agent_current: str,
    messages: list[Message],
    soft_max_chars: int,
) -> tuple[str, bool, str, bool, Usage]:
    """双块对账。返回 (user_memory, user_changed, agent_memory, agent_changed, usage);
    changed=false 的块回显【现值】而非模型 echo(模型可能漏抄/改写)。"""
    prompt = (
        f"CURRENT USER MEMORY:\n{user_current or '(empty)'}\n\n"
        f"CURRENT AGENT MEMORY:\n{agent_current or '(empty)'}\n\n"
        f"RECENT CONVERSATION:\n{_render(messages)}"
    )
    result = await provider.complete(
        CompletionRequest(
            system=_SYSTEM.format(soft=soft_max_chars),
            messages=[Message(role=Role.USER, text=prompt)],
            tools=[],
        )
    )
    # 解析失败 → 抛 MemoryParseError(handler 收敛为 INTERNAL)→ 后端不推进水位线、下次重试。
    user_mem, user_changed, agent_mem, agent_changed = _parse(result.message.text)
    return (
        user_mem if user_changed else user_current,
        user_changed,
        agent_mem if agent_changed else agent_current,
        agent_changed,
        result.usage,
    )
