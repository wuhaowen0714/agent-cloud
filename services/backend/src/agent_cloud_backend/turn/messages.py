from __future__ import annotations

from agent_cloud_common import Message as CommonMessage
from agent_cloud_common import Role, ToolCall, ToolResult

from agent_cloud_backend.models.message import Message as OrmMessage


def strip_unanswered_user_messages(history: list) -> list:
    """丢弃没有助手回复的 user 消息——被取消/出错的回合只在库里留下了 user 消息
    (助手消息仅在 TurnDone 成功时才落库)。否则模型会把上一轮没答完的问题也一并
    回答,或这些消息被折叠进摘要造成污染。判定:某 user 消息之后紧跟的不是助手/工具
    消息(是另一个 user,或已到末尾)。assemble(发给模型)与 compaction(折叠进摘要)
    共用此清洗,保证两条路径看到的历史一致。"""
    kept = []
    for i, m in enumerate(history):
        if m.role == "user":
            nxt = history[i + 1] if i + 1 < len(history) else None
            if nxt is None or nxt.role == "user":
                continue
        kept.append(m)
    return kept


def is_subagent_orm(message: OrmMessage) -> bool:
    """ORM 消息是否属于子 agent(content.parent_call_id 非空)。子消息只服务前端历史重建,
    绝不进发给 LLM / 压缩摘要 / 记忆抽取的集合 —— 否则子 agent 的中间过程(web_search、读文件等)
    会作为主 agent 的历史动作重新喂回模型,污染主上下文、撑大 token、可能触发网关严格校验
    (破坏 subagent "主 agent 只见 task 结果摘要" 的隔离不变量)。前端历史 API 仍返回它们供重建。"""
    return bool((message.content or {}).get("parent_call_id"))


def orm_to_common(message: OrmMessage) -> CommonMessage:
    content = message.content or {}
    return CommonMessage(
        role=Role(message.role),
        text=content.get("text", ""),
        images=content.get("images") or [],
        tool_calls=[ToolCall(**c) for c in content.get("tool_calls", [])],
        tool_results=[ToolResult(**r) for r in content.get("tool_results", [])],
        parent_call_id=content.get("parent_call_id", ""),
    )


def common_to_content(message: CommonMessage) -> dict:
    return {
        "text": message.text,
        "images": list(message.images),
        "tool_calls": [
            {"id": c.id, "name": c.name, "arguments": c.arguments} for c in message.tool_calls
        ],
        "tool_results": [
            {"call_id": r.call_id, "content": r.content, "is_error": r.is_error}
            for r in message.tool_results
        ],
        "parent_call_id": message.parent_call_id,
    }


def active_images(history: list, current_images: list[str]) -> list[str]:
    """本回合发给模型的图片:本轮新上传优先;否则回退到 history 里最近一条带 images 的 user
    消息(延续追问)。history 已按压缩边界过滤,被折叠的旧图天然不回灌(spec: 活跃图片生命周期)。"""
    if current_images:
        return list(current_images)
    for m in reversed(history):
        if m.role == "user":
            imgs = (m.content or {}).get("images") or []
            if imgs:
                return list(imgs)
    return []
