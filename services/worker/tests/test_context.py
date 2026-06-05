from agent_cloud_common import ContextDocument, MemoryItem, SkillRef
from agent_cloud_worker.context import build_system_prompt


def test_layers_user_then_agent_docs():
    out = build_system_prompt(
        documents=[
            ContextDocument(scope="agent", type="AGENTS", content="AGENT BODY"),
            ContextDocument(scope="user", type="USER", content="USER BODY"),
        ],
        memory=[],
        skills=[],
    )
    assert "USER BODY" in out and "AGENT BODY" in out
    # 用户级文档排在 agent 级之前
    assert out.index("USER BODY") < out.index("AGENT BODY")


def test_includes_memory_and_skills():
    out = build_system_prompt(
        documents=[],
        memory=[MemoryItem(scope="user", content="likes tea")],
        skills=[
            SkillRef(name="weather", description="get weather", location="/skills/weather/SKILL.md")
        ],
    )
    assert "likes tea" in out
    assert "weather" in out
    assert "/skills/weather/SKILL.md" in out
    assert "<available_skills>" in out


def test_empty_inputs_produce_empty_string():
    assert build_system_prompt(documents=[], memory=[], skills=[]) == ""
