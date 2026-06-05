import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_session
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.user import UserRepository
from agent_cloud_backend.schemas.user import UserCreate, UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, session: AsyncSession = Depends(get_session)):
    user = await UserRepository(session).create(User(email=body.email))
    await session.commit()
    return user


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    user = await UserRepository(session).get(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return user
