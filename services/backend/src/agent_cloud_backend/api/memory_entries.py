import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.repositories.memory_entry import MemoryEntryRepository
from agent_cloud_backend.schemas.memory_entry import MemoryAppend, MemoryRead

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
async def append_memory(body: MemoryAppend, session: AsyncSession = Depends(get_session)):
    entry = await MemoryEntryRepository(session).append(
        body.scope, body.owner_id, body.content, body.source_session_id
    )
    await session.commit()
    return entry


@router.get("", response_model=list[MemoryRead])
async def list_memory(
    scope: str, owner_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    return await MemoryEntryRepository(session).list_for_context(scope, owner_id)
