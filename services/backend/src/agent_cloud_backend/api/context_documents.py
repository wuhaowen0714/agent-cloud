import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_current_user, get_session
from agent_cloud_backend.api.ownership import resolve_owner
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.context_document import ContextDocumentRepository
from agent_cloud_backend.schemas.context_document import (
    ContextDocumentRead,
    ContextDocumentUpsert,
)

router = APIRouter(prefix="/context-documents", tags=["context-documents"])


@router.put("", response_model=ContextDocumentRead)
async def upsert_document(
    body: ContextDocumentUpsert,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    owner_id = await resolve_owner(body.scope, body.agent_id, user.id, session)
    doc = await ContextDocumentRepository(session).upsert(
        body.scope, body.type, owner_id, body.content
    )
    await session.commit()
    await session.refresh(doc)
    return doc


@router.get("", response_model=list[ContextDocumentRead])
async def list_documents(
    scope: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    agent_id: uuid.UUID | None = None,
):
    owner_id = await resolve_owner(scope, agent_id, user.id, session)
    return await ContextDocumentRepository(session).list_for_owner(scope, owner_id)
