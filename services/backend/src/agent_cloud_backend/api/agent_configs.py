import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete as sql_delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from agent_cloud_backend.api.deps import get_current_user, get_session
from agent_cloud_backend.api.ownership import owned_agent
from agent_cloud_backend.models.agent_config import AgentConfig
from agent_cloud_backend.models.context_document import ContextDocument
from agent_cloud_backend.models.memory_entry import MemoryEntry
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.agent_config import AgentConfigRepository
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.repositories.skill import AgentSkillEnableRepository, SkillRepository
from agent_cloud_backend.schemas.agent_config import (
    AgentConfigCreate,
    AgentConfigRead,
    AgentConfigUpdate,
)
from agent_cloud_backend.skills.deps import get_object_store, get_skill_registry_root
from agent_cloud_backend.skills.service import enable_builtin_skills, ensure_builtin_skills
from agent_cloud_backend.skills.store import ObjectStore

router = APIRouter(prefix="/agent-configs", tags=["agent-configs"])


@router.post("", response_model=AgentConfigRead, status_code=status.HTTP_201_CREATED)
async def create_agent_config(
    body: AgentConfigCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    # 经依赖注入(而非直调 deps 函数):测试用 dependency_overrides 换临时 store/registry
    store: ObjectStore = Depends(get_object_store),
    registry_root: Path = Depends(get_skill_registry_root),
):
    agent = await AgentConfigRepository(session).create(
        AgentConfig(user_id=user.id, **body.model_dump())
    )
    # 新 agent 内置技能开箱即用:先 ensure(防止从未 GET /skills 的路径建出
    # 无内置技能的 agent),再默认启用全部 registry 来源技能。
    skill_repo = SkillRepository(session)
    await ensure_builtin_skills(
        session=session, user_id=user.id, registry_root=registry_root, repo=skill_repo, store=store
    )
    await enable_builtin_skills(
        agent_config_id=agent.id, user_id=user.id,
        repo=skill_repo, enable_repo=AgentSkillEnableRepository(session),
    )
    await session.commit()
    return agent


@router.get("", response_model=list[AgentConfigRead])
async def list_agent_configs(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    return await AgentConfigRepository(session).list_by_user(user.id)


@router.patch("/{agent_id}", response_model=AgentConfigRead)
async def update_agent_config(
    agent_id: uuid.UUID,
    body: AgentConfigUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    agent = await owned_agent(agent_id, user.id, session)
    fields = body.model_dump(exclude_unset=True)
    if "name" in fields:  # 改名是一等 UI 操作:服务端兜底校验(与 session title 同规)
        name = (fields["name"] or "").strip()
        if not name or len(name) > 200:
            raise HTTPException(status_code=422, detail="name must be 1-200 chars")
        fields["name"] = name
    for field, value in fields.items():
        setattr(agent, field, value)
    await session.commit()
    await session.refresh(agent)
    return agent


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent_config(
    agent_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """删除 agent 并连带其全部会话(消息 CASCADE)、agent 级记忆与指令文档。

    任一会话仍在跑(原子守卫删不掉)→ 409 并整体回滚(get_session 依赖丢弃未提交事务);
    agent_skill_enables 由 FK CASCADE 自动清。"""
    agent = await owned_agent(agent_id, user.id, session)  # 404
    srepo = SessionRepository(session)
    await srepo.delete_idle_for_agent(agent_id)
    if await srepo.count_for_agent(agent_id) > 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="agent busy")
    await session.execute(
        sql_delete(MemoryEntry).where(
            MemoryEntry.scope == "agent", MemoryEntry.owner_id == agent_id
        )
    )
    await session.execute(
        sql_delete(ContextDocument).where(
            ContextDocument.scope == "agent", ContextDocument.owner_id == agent_id
        )
    )
    await session.delete(agent)
    try:
        await session.commit()
    except StaleDataError as exc:
        # 并发双删:败者的 ORM DELETE 匹配 0 行 → 当作"已不存在"而非 500
        raise HTTPException(status_code=404, detail="agent config not found") from exc
    except IntegrityError as exc:
        # 与并发 POST /sessions 撞 FK(RESTRICT):有人正往该 agent 下建会话 → 当 busy
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="agent busy") from exc
