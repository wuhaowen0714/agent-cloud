import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_current_user, get_session
from agent_cloud_backend.api.ownership import resolve_owner
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.memory_entry import MemoryConflict, MemoryEntryRepository
from agent_cloud_backend.schemas.memory_entry import MemoryBlockRead, MemoryBlockWrite

router = APIRouter(prefix="/memory", tags=["memory"])


async def _write(repo: MemoryEntryRepository, scope, owner_id, content) -> MemoryBlockRead:
    cur = await repo.get_current(scope, owner_id)
    try:
        entry = await repo.write_version(
            scope, owner_id, content, None, expected_version=cur.version if cur else 0
        )
    except MemoryConflict as e:  # 并发改写:让客户端重取后重试
        raise HTTPException(status_code=409, detail="memory was modified concurrently") from e
    return MemoryBlockRead(
        scope=entry.scope, owner_id=entry.owner_id, content=entry.content, version=entry.version
    )


@router.get("", response_model=MemoryBlockRead)
async def get_memory(
    scope: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    agent_id: uuid.UUID | None = None,
):
    owner_id = await resolve_owner(scope, agent_id, user.id, session)
    cur = await MemoryEntryRepository(session).get_current(scope, owner_id)
    return MemoryBlockRead(
        scope=scope,
        owner_id=owner_id,
        content=cur.content if cur else "",
        version=cur.version if cur else 0,
    )


@router.put("", response_model=MemoryBlockRead)
async def put_memory(
    body: MemoryBlockWrite,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    owner_id = await resolve_owner(body.scope, body.agent_id, user.id, session)
    block = await _write(MemoryEntryRepository(session), body.scope, owner_id, body.content)
    await session.commit()
    return block


@router.delete("", response_model=MemoryBlockRead)
async def clear_memory(
    scope: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    agent_id: uuid.UUID | None = None,
):
    owner_id = await resolve_owner(scope, agent_id, user.id, session)
    block = await _write(MemoryEntryRepository(session), scope, owner_id, "")  # 清空 = 写空块新版本
    await session.commit()
    return block
