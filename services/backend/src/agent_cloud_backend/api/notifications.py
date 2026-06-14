from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_current_user, get_session
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.notification import NotificationRepository
from agent_cloud_backend.schemas.notification import MarkDeliveredRequest, NotificationRead

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationRead])
async def list_notifications(
    session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)
):
    return await NotificationRepository(session).list_undelivered(user.id)


@router.post("/mark-delivered", status_code=status.HTTP_204_NO_CONTENT)
async def mark_delivered(
    body: MarkDeliveredRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    await NotificationRepository(session).mark_delivered(body.ids, user.id)
    await session.commit()
