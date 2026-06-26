from __future__ import annotations

import re
import uuid

from agent_cloud.v1 import worker_pb2
from agent_cloud_common.codec import msg_to_proto
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.config import get_settings
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.models.skill import Skill
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.context_document import ContextDocumentRepository
from agent_cloud_backend.repositories.memory_entry import MemoryEntryRepository
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.skills.materialize import skill_location
from agent_cloud_backend.turn.credentials import resolve_session_key
from agent_cloud_backend.turn.messages import (
    active_images,
    is_subagent_orm,
    orm_to_common,
    strip_unanswered_user_messages,
)

# 手机 App 运行环境提示:注入 system prompt 引导优先用 set_alarm/add_calendar_event/
# start_navigation(直接操作手机系统闹钟/日历/地图)而非 schedule_task(云端周期任务)。web 端不注入。
_MOBILE_ENV_DOC = (
    "【运行环境】你正运行在用户的 Android 手机 App 上,可以直接操作手机系统。\n"
    "- 用户要「设闹钟 / 在某个时刻响铃提醒」→ 优先用 set_alarm 直接设手机系统闹钟,"
    "不要用 schedule_task。\n"
    "- 用户要「加日程 / 日历事件 / 会议安排」→ 优先用 add_calendar_event,"
    "直接加手机系统日历。\n"
    "- 用户要「导航 / 带我去 / 怎么走 / 开车去某地」→ 用 start_navigation 唤起手机地图"
    "(高德/百度)开始导航,destination 传地点名即可、无需坐标。\n"
    "- 这些工具会在手机上弹出系统应用 / 地图预填,由用户确认。\n"
    "- schedule_task 是云端周期任务(到点让你再运行一次发应用内通知),不是系统闹钟;"
    "只在用户明确要「周期性 / 让 AI 到点替我做某事」时才用。"
)

# 文本模型(不可见图片)下,历史 user 文本里独占一行的【工作区图片路径】降级为 [图片] 占位 ——
# 否则模型看到 composeUpload 拼的 "read with read_file" + jpg 路径,会去 read_file 读图(读图片
# 二进制无意义、徒增一次工具往返,正是"切文本模型后怪怪的/又在读文件"的来源)。非图片路径
# (文档等)不动,文本模型仍可 read_file 读它们。
_IMAGE_PATH_LINE = re.compile(
    r"^(?:uploads?|media)/[^\n]+?\.(?:png|jpe?g|gif|webp|bmp)$",
    re.IGNORECASE | re.MULTILINE,
)


def _demote_image_paths(text: str) -> str:
    return _IMAGE_PATH_LINE.sub("[图片]", text)


async def build_run_turn_request(
    db: AsyncSession,
    session: Session,
    *,
    sandbox_endpoint: str,
    user_message: str,
    exclude_message_id: uuid.UUID | None,
    enabled_skills: list[Skill] | None = None,
    work_subdir: str | None = None,
    sandbox_token: str = "",
    is_scheduled_run: bool = False,
    images: list[str] | None = None,
    client_platform: str = "web",
) -> worker_pb2.RunTurnRequest:
    agent = await AgentConfigRepository(db).get(session.agent_config_id)
    doc_repo = ContextDocumentRepository(db)
    user_docs = await doc_repo.list_for_owner("user", session.user_id)
    agent_docs = await doc_repo.list_for_owner("agent", session.agent_config_id)
    mem_repo = MemoryEntryRepository(db)
    # 注入"当前块"(每作用域 version 最大的一条),不再是最近 N 条(spec 2026-06-09)。
    mem_blocks = [
        b
        for b in (
            await mem_repo.get_current("user", session.user_id),
            await mem_repo.get_current("agent", session.agent_config_id),
        )
        if b is not None and b.content.strip()
    ]
    history = await MessageRepository(db).list_by_session(session.id)
    # 压缩后:已折叠进 summary 的消息(seq <= summary_through_seq)不再逐字发,
    # 改由 history_summary 承载;未压缩会话的 summary_through_seq=-1,等价于不过滤。
    history = [
        m
        for m in history
        if m.id != exclude_message_id
        and m.seq > session.summary_through_seq
        and not is_subagent_orm(m)  # 子 agent 中间过程绝不喂回主 agent(只服务前端历史重建)
    ]
    history = strip_unanswered_user_messages(history)

    settings = get_settings()
    # BYO-Key:按 session.credential_id 取本人凭据解密;None/不属本人 → ("",""),worker 回退平台。
    api_key, base_url = await resolve_session_key(
        db, session.credential_id, session.user_id, settings
    )
    # 当前模型不支持图片输入时,绝不能发图片 vision params —— sophnet 返回 400 "model X do not
    # support image params"、整回合崩(切回文本模型后发任何消息都中招,哪怕只是"你好":历史活跃图
    # 会被 active_images 回灌成当前回合的 vision 输入)。turn_images 是图片送达 worker 的唯一通道
    # (worker 读成 data_uri 注入 content;history 消息的 proto 不带 images),故置空即彻底不发图。
    # 仅平台模型(credential_id None)能用 is_vision_model 权威判定;BYOK 的 vision 后端无标记
    # (credential 不存 visionModels),保守不动、避免误清 BYOK vision 模型。
    strip_images = session.credential_id is None and not settings.is_vision_model(session.model)

    def _to_proto(m):
        c = orm_to_common(m)
        # 文本模型:历史 user 文本里的图片路径降级为 [图片](仅清洗发给 LLM 的 transient 副本,
        # 绝不动库里原文 —— 前端气泡渲染、切回 vision 模型恢复都依赖原文)。
        if strip_images and m.role == "user" and c.text:
            c.text = _demote_image_paths(c.text)
        return msg_to_proto(c)

    return worker_pb2.RunTurnRequest(
        session_id=str(session.id),
        user_id=str(session.user_id),
        agent=worker_pb2.Agent(
            model=session.model,
            provider=("sophnet" if session.credential_id is None else "custom"),
            enabled_tools=list(agent.enabled_tools),
            api_key=api_key,
            base_url=base_url,
        ),
        documents=[
            # 手机 App 置顶注入运行环境提示,引导优先用 set_alarm/add_calendar_event
            *(
                [worker_pb2.Doc(scope="env", type="client", content=_MOBILE_ENV_DOC)]
                if client_platform == "mobile"
                else []
            ),
            *(
                worker_pb2.Doc(scope=d.scope, type=d.type, content=d.content)
                for d in [*user_docs, *agent_docs]
                if d.content.strip()  # 跳过空文档(如被清空的 AGENTS),不往 prompt 里塞空段
            ),
        ],
        memory=[worker_pb2.Mem(scope=b.scope, content=b.content) for b in mem_blocks],
        skills=[
            worker_pb2.Skill(
                name=sk.name, description=sk.description, location=skill_location(sk.name)
            )
            for sk in (enabled_skills or [])
        ],
        messages=[_to_proto(m) for m in history],
        user_message=user_message,
        turn_images=([] if strip_images else active_images(history, images or [])),
        sandbox_endpoint=sandbox_endpoint,
        work_subdir=work_subdir if work_subdir is not None else session.work_subdir,
        history_summary=session.summary,
        sandbox_token=sandbox_token,
        is_scheduled_run=is_scheduled_run,
        client=client_platform,  # worker 据此过滤仅 mobile 可执行的工具(set_alarm/add_calendar)
    )
