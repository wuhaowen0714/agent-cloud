import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_current_user, get_session
from agent_cloud_backend.api.ownership import resolve_owner
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.memory_entry import MemoryEntryRepository
from agent_cloud_backend.schemas.memory_entry import MemoryAppend, MemoryRead

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
async def append_memory(
    body: MemoryAppend,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    owner_id = await resolve_owner(body.scope, body.agent_id, user.id, session)
    entry = await MemoryEntryRepository(session).append(
        body.scope, owner_id, body.content, body.source_session_id
    )
    await session.commit()
    return entry


@router.get("", response_model=list[MemoryRead])
async def list_memory(
    scope: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    agent_id: uuid.UUID | None = None,
):
    owner_id = await resolve_owner(scope, agent_id, user.id, session)
    return await MemoryEntryRepository(session).list_for_context(scope, owner_id)
