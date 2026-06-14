import uuid

from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.skill import Skill
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.skill import (
    AgentSkillEnableRepository,
    SkillRepository,
)


async def _user(session) -> uuid.UUID:
    u = User(email=f"{uuid.uuid4()}@e.com")
    session.add(u)
    await session.flush()
    return u.id


async def _agent(session, user_id) -> uuid.UUID:
    a = AgentConfig(user_id=user_id, name="a")
    session.add(a)
    await session.flush()
    return a.id


def _skill(user_id, name) -> Skill:
    return Skill(
        user_id=user_id,
        name=name,
        description="d",
        source="registry",
        version="1.0.0",
        requires={},
        package_ref=f"users/{user_id}/skills/{name}",
    )


async def test_list_by_user_sorted(session):
    uid = await _user(session)
    repo = SkillRepository(session)
    await repo.create(_skill(uid, "beta"))
    await repo.create(_skill(uid, "alpha"))
    names = [s.name for s in await repo.list_by_user(uid)]
    assert names == ["alpha", "beta"]


async def test_get_by_user_and_name(session):
    uid = await _user(session)
    repo = SkillRepository(session)
    await repo.create(_skill(uid, "alpha"))
    assert (await repo.get_by_user_and_name(uid, "alpha")) is not None
    assert (await repo.get_by_user_and_name(uid, "nope")) is None


async def test_set_enabled_upsert(session):
    uid = await _user(session)
    aid = await _agent(session, uid)
    s = await SkillRepository(session).create(_skill(uid, "alpha"))
    repo = AgentSkillEnableRepository(session)
    row = await repo.set_enabled(aid, s.id, True)
    assert row.enabled is True
    row2 = await repo.set_enabled(aid, s.id, False)
    assert row2.enabled is False  # 同一行更新,不新增


async def test_replace_enabled_set(session):
    uid = await _user(session)
    aid = await _agent(session, uid)
    srepo = SkillRepository(session)
    s1 = await srepo.create(_skill(uid, "alpha"))
    s2 = await srepo.create(_skill(uid, "beta"))
    s3 = await srepo.create(_skill(uid, "gamma"))
    repo = AgentSkillEnableRepository(session)
    await repo.replace_enabled_set(aid, [s1.id, s2.id])
    assert {s.name for s in await repo.list_enabled_for_agent(aid)} == {"alpha", "beta"}
    # 替换:去掉 beta,加 gamma
    await repo.replace_enabled_set(aid, [s1.id, s3.id])
    assert {s.name for s in await repo.list_enabled_for_agent(aid)} == {"alpha", "gamma"}


async def test_list_enabled_excludes_disabled(session):
    uid = await _user(session)
    aid = await _agent(session, uid)
    s = await SkillRepository(session).create(_skill(uid, "alpha"))
    repo = AgentSkillEnableRepository(session)
    await repo.set_enabled(aid, s.id, False)
    assert await repo.list_enabled_for_agent(aid) == []
