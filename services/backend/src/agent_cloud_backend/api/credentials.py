from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend import crypto
from agent_cloud_backend.api.deps import get_current_user, get_session
from agent_cloud_backend.api.ownership import owned_credential
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.models.session import Session
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.provider_credential import ProviderCredentialRepository
from agent_cloud_backend.schemas.credential import CredentialCreate, CredentialRead

router = APIRouter(prefix="/credentials", tags=["credentials"])


@router.post("", response_model=CredentialRead, status_code=status.HTTP_201_CREATED)
async def create_credential(
    body: CredentialCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    key = crypto.load_credential_key(settings.credential_key)
    row = await ProviderCredentialRepository(db).create(
        user_id=user.id,
        name=body.name,
        base_url=body.base_url,
        api_key_encrypted=crypto.encrypt(body.api_key, key),
        masked=crypto.mask(body.api_key),
        models=body.models,
    )
    await db.commit()
    return row


@router.get("", response_model=list[CredentialRead])
async def list_credentials(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    return await ProviderCredentialRepository(db).list_for_user(user.id)


@router.delete("/{cred_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    cred_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    row = await owned_credential(cred_id, user.id, db)
    # 把指向该凭据的 session.credential_id 置空(FK SET NULL 已兜底,显式清更直观),
    # 删除后这些会话回退平台 sophnet 全局 Key。
    await db.execute(
        update(Session)
        .where(Session.user_id == user.id, Session.credential_id == cred_id)
        .values(credential_id=None)
    )
    await db.delete(row)
    await db.commit()
