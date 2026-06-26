from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.message import Message as OrmMessage
from agent_cloud_backend.models.skill import Skill
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.context_document import ContextDocumentRepository
from agent_cloud_backend.repositories.memory_entry import MemoryEntryRepository
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.repositories.skill import SkillRepository
from agent_cloud_backend.repositories.user import UserRepository
from agent_cloud_backend.turn.assemble import build_run_turn_request


async def test_build_request_from_db(session):
    user = await UserRepository(session).create(User(email="a@example.com"))
    await session.flush()
    agent = await AgentConfigRepository(session).create(
        AgentConfig(
            user_id=user.id,
            name="coder",
            enabled_tools=["bash"],
        )
    )
    await session.flush()
    s = await SessionRepository(session).create_for(user.id, agent.id, None, model="m")
    await session.flush()
    await ContextDocumentRepository(session).upsert("user", "USER", user.id, "# user")
    await ContextDocumentRepository(session).upsert("agent", "AGENTS", agent.id, "# agent")
    await MemoryEntryRepository(session).write_version(
        "user", user.id, "likes tea", None, expected_version=0
    )
    # history: one COMPLETE prior turn (user + assistant). 未完成(无助手回复)的 user
    # 消息会被 _strip_unanswered_user_messages 丢掉(见专项单测)。
    await MessageRepository(session).append(
        s.id, OrmMessage(session_id=s.id, seq=0, role="user", content={"text": "earlier"})
    )
    await MessageRepository(session).append(
        s.id,
        OrmMessage(
            session_id=s.id,
            seq=0,
            role="assistant",
            content={"text": "replied", "tool_calls": [], "tool_results": []},
        ),
    )
    await session.commit()

    req = await build_run_turn_request(
        session,
        s,
        sandbox_endpoint="localhost:50051",
        user_message="now",
        exclude_message_id=None,
    )
    assert req.session_id == str(s.id) and req.user_id == str(user.id)
    assert req.agent.model == "m" and list(req.agent.enabled_tools) == ["bash"]
    assert {d.type for d in req.documents} == {"USER", "AGENTS"}
    assert any(m.content == "likes tea" for m in req.memory)
    assert [m.text for m in req.messages] == ["earlier", "replied"]  # 完整历史保留
    assert req.user_message == "now"
    assert req.sandbox_endpoint == "localhost:50051"
    assert req.work_subdir == s.work_subdir


async def test_build_request_excludes_subagent_messages(session):
    # CRITICAL 回归:子 agent 消息(content.parent_call_id 非空)绝不进发给 LLM 的 messages
    # —— 否则子过程(web_search 等)会作为主 agent 历史重新喂回模型、污染主上下文。
    user = await UserRepository(session).create(User(email="sub@example.com"))
    await session.flush()
    agent = await AgentConfigRepository(session).create(
        AgentConfig(user_id=user.id, name="coder", enabled_tools=["bash"])
    )
    await session.flush()
    s = await SessionRepository(session).create_for(user.id, agent.id, None, model="m")
    await session.flush()
    await MessageRepository(session).append(
        s.id, OrmMessage(session_id=s.id, seq=0, role="user", content={"text": "主问题"})
    )
    await MessageRepository(session).append(
        s.id,
        OrmMessage(
            session_id=s.id, seq=0, role="assistant",
            content={"text": "主回答", "tool_calls": [], "tool_results": []},
        ),
    )
    # 子 agent 中间消息(parent_call_id 指向 task 调用):只服务前端重建,不该喂 LLM
    await MessageRepository(session).append(
        s.id,
        OrmMessage(
            session_id=s.id, seq=0, role="assistant",
            content={"text": "子搜索", "tool_calls": [], "tool_results": [],
                     "parent_call_id": "task1"},
        ),
    )
    await session.commit()

    req = await build_run_turn_request(
        session, s, sandbox_endpoint="localhost:50051", user_message="now",
        exclude_message_id=None,
    )
    # 主 agent 消息保留;子 agent 消息(parent_call_id)被排除出喂给模型的历史
    assert [m.text for m in req.messages] == ["主问题", "主回答"]


async def test_memory_injects_only_current_block(session):
    user = await UserRepository(session).create(User(email="b@example.com"))
    await session.flush()
    agent = await AgentConfigRepository(session).create(
        AgentConfig(user_id=user.id, name="a")
    )
    await session.flush()
    s = await SessionRepository(session).create_for(user.id, agent.id, None, model="m")
    await session.flush()
    repo = MemoryEntryRepository(session)
    await repo.write_version("user", user.id, "OLD block", None, expected_version=0)
    await repo.write_version("user", user.id, "NEW block", None, expected_version=1)
    await session.commit()

    req = await build_run_turn_request(
        session, s, sandbox_endpoint="x", user_message="hi", exclude_message_id=None
    )
    user_mems = [m.content for m in req.memory if m.scope == "user"]
    assert user_mems == ["NEW block"]  # 只注入最新版本,不是历史所有条


async def test_build_request_excludes_current_user_message(session):
    user = await UserRepository(session).create(User(email="b@example.com"))
    await session.flush()
    agent = await AgentConfigRepository(session).create(
        AgentConfig(user_id=user.id, name="c")
    )
    await session.flush()
    s = await SessionRepository(session).create_for(user.id, agent.id, None, model="m")
    await session.flush()
    current = await MessageRepository(session).append(
        s.id, OrmMessage(session_id=s.id, seq=0, role="user", content={"text": "current"})
    )
    await session.commit()
    req = await build_run_turn_request(
        session,
        s,
        sandbox_endpoint="x",
        user_message="current",
        exclude_message_id=current.id,
    )
    assert req.messages == []  # the only message was excluded


async def test_non_vision_platform_model_strips_all_images(session):
    # 根因回归:平台文本模型(非 vision)切回后,历史/活跃图片都不能作 image params 发出 —— 否则
    # sophnet 400 "model X do not support image params"、整回合崩(连发"你好"都没响应)。
    user = await UserRepository(session).create(User(email="txt@example.com"))
    await session.flush()
    agent = await AgentConfigRepository(session).create(AgentConfig(user_id=user.id, name="a"))
    await session.flush()
    # 平台模型(credential_id None) + 非 vision(DeepSeek-V4-Pro 不在 vision_models)
    s = await SessionRepository(session).create_for(
        user.id, agent.id, None, model="DeepSeek-V4-Pro"
    )
    await session.flush()
    await MessageRepository(session).append(
        s.id,
        OrmMessage(
            session_id=s.id, seq=0, role="user",
            content={"text": "看图", "images": ["uploads/a.jpg"]},
        ),
    )
    await MessageRepository(session).append(
        s.id,
        OrmMessage(
            session_id=s.id, seq=0, role="assistant",
            content={"text": "是猫", "tool_calls": [], "tool_results": []},
        ),
    )
    await session.commit()

    req = await build_run_turn_request(
        session, s, sandbox_endpoint="x", user_message="你好",
        exclude_message_id=None, images=["uploads/b.jpg"],
    )
    # turn_images 是图片送达 worker 的唯一通道,文本模型下置空 → 彻底不发图、不会 400。
    assert list(req.turn_images) == []
    assert [m.text for m in req.messages] == ["看图", "是猫"]  # 文本历史照常保留


async def test_vision_platform_model_keeps_images(session):
    # 对照:平台 vision 模型照常发图(历史 images 保留 + active_images 回灌当前回合)。
    user = await UserRepository(session).create(User(email="vis@example.com"))
    await session.flush()
    agent = await AgentConfigRepository(session).create(AgentConfig(user_id=user.id, name="a"))
    await session.flush()
    s = await SessionRepository(session).create_for(
        user.id, agent.id, None, model="Kimi-K2.6"  # 平台 vision 模型
    )
    await session.flush()
    await MessageRepository(session).append(
        s.id,
        OrmMessage(
            session_id=s.id, seq=0, role="user",
            content={"text": "看图", "images": ["uploads/a.jpg"]},
        ),
    )
    await MessageRepository(session).append(
        s.id,
        OrmMessage(
            session_id=s.id, seq=0, role="assistant",
            content={"text": "是猫", "tool_calls": [], "tool_results": []},
        ),
    )
    await session.commit()

    req = await build_run_turn_request(
        session, s, sandbox_endpoint="x", user_message="再看", exclude_message_id=None,
    )
    assert list(req.turn_images) == ["uploads/a.jpg"]  # vision 模型:回灌历史活跃图照常发


async def test_build_request_includes_enabled_skills(session):
    user = await UserRepository(session).create(User(email="sk@example.com"))
    await session.flush()
    agent = await AgentConfigRepository(session).create(
        AgentConfig(user_id=user.id, name="c")
    )
    await session.flush()
    s = await SessionRepository(session).create_for(user.id, agent.id, None, model="m")
    await session.flush()
    skill = await SkillRepository(session).create(
        Skill(
            user_id=user.id, name="greet", description="say hi", source="registry",
            version="1.0.0", requires={}, package_ref=f"users/{user.id}/skills/greet",
        )
    )
    await session.commit()

    req = await build_run_turn_request(
        session, s, sandbox_endpoint="x", user_message="hi",
        exclude_message_id=None, enabled_skills=[skill],
    )
    assert len(req.skills) == 1
    assert req.skills[0].name == "greet"
    assert req.skills[0].description == "say hi"
    assert req.skills[0].location == ".skills/greet/SKILL.md"


async def test_build_request_skills_default_empty(session):
    user = await UserRepository(session).create(User(email="sk2@example.com"))
    await session.flush()
    agent = await AgentConfigRepository(session).create(
        AgentConfig(user_id=user.id, name="c")
    )
    await session.flush()
    s = await SessionRepository(session).create_for(user.id, agent.id, None, model="m")
    await session.commit()
    req = await build_run_turn_request(
        session, s, sandbox_endpoint="x", user_message="hi", exclude_message_id=None
    )
    assert list(req.skills) == []


async def test_build_request_work_subdir_override(session):
    user = await UserRepository(session).create(User(email="ws@example.com"))
    await session.flush()
    agent = await AgentConfigRepository(session).create(
        AgentConfig(user_id=user.id, name="c")
    )
    await session.flush()
    s = await SessionRepository(session).create_for(user.id, agent.id, None, model="m")
    await session.commit()
    # 默认:用 session.work_subdir
    req = await build_run_turn_request(
        session, s, sandbox_endpoint="x", user_message="hi", exclude_message_id=None
    )
    assert req.work_subdir == s.work_subdir
    # 覆盖(docker 沙箱用 "." —— workspace 已挂到 /workspace,不再二次嵌套)
    req2 = await build_run_turn_request(
        session, s, sandbox_endpoint="x", user_message="hi",
        exclude_message_id=None, work_subdir=".",
    )
    assert req2.work_subdir == "."


async def test_build_request_passes_client_platform(session):
    # wiring 回归:client_platform 必须落进 RunTurnRequest.client,worker 据此过滤仅 mobile 可
    # 执行的工具(set_alarm/add_calendar)。漏传则 worker 收默认 "" → 连 mobile 也静默不暴露。
    user = await UserRepository(session).create(User(email="cli@example.com"))
    await session.flush()
    agent = await AgentConfigRepository(session).create(AgentConfig(user_id=user.id, name="c"))
    await session.flush()
    s = await SessionRepository(session).create_for(user.id, agent.id, None, model="m")
    await session.commit()
    # 默认 web(web 前端不发 client → TurnRequest.client 默认 web → 这里默认 web)
    req_web = await build_run_turn_request(
        session, s, sandbox_endpoint="x", user_message="hi", exclude_message_id=None
    )
    assert req_web.client == "web"
    # mobile 透传
    req_mobile = await build_run_turn_request(
        session, s, sandbox_endpoint="x", user_message="hi",
        exclude_message_id=None, client_platform="mobile",
    )
    assert req_mobile.client == "mobile"


async def test_build_request_drops_summarized_and_sends_history_summary(session):
    # 压缩后:seq <= summary_through_seq 的消息不再逐字发,改为发 history_summary;
    # 之后的消息(seq > 边界)仍逐字保留(spec §9)。
    user = await UserRepository(session).create(User(email="sum@example.com"))
    await session.flush()
    agent = await AgentConfigRepository(session).create(
        AgentConfig(user_id=user.id, name="c")
    )
    await session.flush()
    s = await SessionRepository(session).create_for(user.id, agent.id, None, model="m")
    await session.flush()
    # seq 0,1 已折叠;seq 2,3 保留
    await MessageRepository(session).append(
        s.id, OrmMessage(session_id=s.id, seq=0, role="user", content={"text": "old-u"})
    )
    await MessageRepository(session).append(
        s.id,
        OrmMessage(
            session_id=s.id, seq=0, role="assistant",
            content={"text": "old-a", "tool_calls": [], "tool_results": []},
        ),
    )
    await MessageRepository(session).append(
        s.id, OrmMessage(session_id=s.id, seq=0, role="user", content={"text": "recent-u"})
    )
    await MessageRepository(session).append(
        s.id,
        OrmMessage(
            session_id=s.id, seq=0, role="assistant",
            content={"text": "recent-a", "tool_calls": [], "tool_results": []},
        ),
    )
    s.summary = "早期摘要"
    s.summary_through_seq = 1
    await session.commit()

    req = await build_run_turn_request(
        session, s, sandbox_endpoint="x", user_message="now", exclude_message_id=None
    )
    assert req.history_summary == "早期摘要"
    assert [m.text for m in req.messages] == ["recent-u", "recent-a"]


def _ns(role: str):
    from types import SimpleNamespace

    return SimpleNamespace(role=role)


def test_strip_unanswered_user_messages_drops_cancelled_turns():
    from agent_cloud_backend.turn.messages import strip_unanswered_user_messages

    h = [
        _ns("user"), _ns("assistant"), _ns("tool"), _ns("assistant"),  # 完整轮 → 保留
        _ns("user"),  # 取消轮(后跟 user)→ 丢
        _ns("user"), _ns("assistant"),  # 完整轮 → 保留
    ]
    assert [m.role for m in strip_unanswered_user_messages(h)] == [
        "user", "assistant", "tool", "assistant", "user", "assistant",
    ]


def test_strip_drops_trailing_unanswered_user_and_handles_empty():
    from agent_cloud_backend.turn.messages import strip_unanswered_user_messages

    h = [_ns("user"), _ns("assistant"), _ns("user")]  # 末尾 user 无回复 → 丢
    assert [m.role for m in strip_unanswered_user_messages(h)] == ["user", "assistant"]
    assert strip_unanswered_user_messages([]) == []
