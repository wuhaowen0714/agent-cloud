from __future__ import annotations

import json
import logging

from agent_cloud_common import CompletionRequest, Message, Role, Usage

from agent_cloud_worker.provider import Provider

logger = logging.getLogger(__name__)

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
Set a *_changed to false and echo the current block if nothing durable changes for that block.
A MOVE changes BOTH blocks — set both *_changed to true."""


class MemoryParseError(Exception):
    """LLM 输出无法解析为 {user_changed, user_memory, agent_changed, agent_memory}。
    视为"提炼失败"(上层不推进水位线、下次重试),而非静默当作"无变化"——
    否则解析失败会被误当 no-op 推进水位线、永久丢掉本可记住的事实。"""


def _try_decode(s: str) -> dict | None:
    """从第一个 { 起 raw_decode(容忍前后说明文字);strict=False 容忍弱模型在字符串值里
    输出裸换行等控制字符。解析不出 dict → None。"""
    start = s.find("{")
    if start < 0:
        return None
    try:
        obj, _ = json.JSONDecoder(strict=False).raw_decode(s[start:])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _parse(text: str) -> tuple[str, bool, str, bool]:
    """解析双块 JSON;缺键/错型/旧式单块输出一律抛 MemoryParseError。

    先对原文整体解码,失败才尝试剥 ``` 围栏——记忆内容本身可能含 ``` 代码段
    (remember 的 content 原样入块),先剥围栏会把合法 JSON 切坏,造成同一会话
    每轮提炼确定性失败(审查 M3)。
    """
    s = text.strip()
    obj = _try_decode(s)
    if obj is None and "```" in s:  # 围栏兜底:```json ... ```(取首对围栏内内容)
        parts = s.split("```")
        if len(parts) >= 3:
            inner = parts[1]
            if inner.lstrip().lower().startswith("json"):
                inner = inner.lstrip()[4:]
            obj = _try_decode(inner.strip())
    if obj is None:
        raise MemoryParseError("no parseable JSON object in output")
    for key in ("user_memory", "agent_memory"):
        if obj.get(key) is None:
            obj[key] = ""  # 容忍 null(弱模型对空块常输出 null)
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
    # MOVE 防御(审查 M1):搬运 = 源块删 + 目标块加,弱模型常一侧 changed 手滑 false——
    # 删那侧生效、加那侧被 echo-guard 吞掉 → 事实从两层同时消失且永不重提。
    # 仅当另一块确实 changed 时信任内容差异,把漏标且输出非空的一侧提升为 changed;
    # 输出为空不提升(防"懒空"误清块);两块都 false 维持纯 echo-guard(不信 garbled echo)。
    if user_changed and not agent_changed and agent_mem.strip() and agent_mem != agent_current:
        logger.warning("reconcile: promoting agent_changed (content differs while user moved)")
        agent_changed = True
    elif agent_changed and not user_changed and user_mem.strip() and user_mem != user_current:
        logger.warning("reconcile: promoting user_changed (content differs while agent moved)")
        user_changed = True
    return (
        user_mem if user_changed else user_current,
        user_changed,
        agent_mem if agent_changed else agent_current,
        agent_changed,
        result.usage,
    )
