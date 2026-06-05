import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.repositories.session import SessionRepository
from agent_cloud_backend.schemas.session import SessionCreate, SessionRead

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
async def create_session(body: SessionCreate, session: AsyncSession = Depends(get_session)):
    s = await SessionRepository(session).create_for(
        body.user_id, body.agent_config_id, body.title
    )
    await session.commit()
    return s


@router.get("", response_model=list[SessionRead])
async def list_sessions(user_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    return await SessionRepository(session).list_by_user(user_id)
