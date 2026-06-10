import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_current_user, get_session
from agent_cloud_backend.api.ownership import owned_user_model
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.user_model import UserModelRepository
from agent_cloud_backend.schemas.user_model import UserModelCreate, UserModelRead

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[UserModelRead])
async def list_models(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    return await UserModelRepository(db).list_by_user(user.id)


@router.post("", response_model=UserModelRead, status_code=status.HTTP_201_CREATED)
async def add_model(
    body: UserModelCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    name = body.model.strip()
    if not name or len(name) > 200:
        raise HTTPException(status_code=422, detail="model must be 1-200 chars")
    row = await UserModelRepository(db).get_or_create(user.id, name)
    await db.commit()
    return row


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    model_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    row = await owned_user_model(model_id, user.id, db)
    await db.delete(row)
    await db.commit()
