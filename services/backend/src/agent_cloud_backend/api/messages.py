import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.models.message import Message
from agent_cloud_backend.repositories.message import MessageRepository
from agent_cloud_backend.schemas.message import MessageCreate, MessageRead

router = APIRouter(prefix="/sessions/{session_id}/messages", tags=["messages"])


@router.post("", response_model=MessageRead, status_code=status.HTTP_201_CREATED)
async def append_message(
    session_id: uuid.UUID, body: MessageCreate, session: AsyncSession = Depends(get_session)
):
    msg = await MessageRepository(session).append(
        session_id,
        Message(
            session_id=session_id,
            seq=0,
            role=body.role,
            content=body.content,
            model=body.model,
            tokens=body.tokens,
        ),
    )
    await session.commit()
    return msg


@router.get("", response_model=list[MessageRead])
async def list_messages(session_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    return await MessageRepository(session).list_by_session(session_id)
