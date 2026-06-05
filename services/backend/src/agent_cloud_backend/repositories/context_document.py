import uuid

from sqlalchemy import select

from agent_cloud_backend.models.context_document import ContextDocument
from agent_cloud_backend.repositories.base import BaseRepository


class ContextDocumentRepository(BaseRepository[ContextDocument]):
    model = ContextDocument

    async def upsert(
        self, scope: str, type: str, owner_id: uuid.UUID, content: str
    ) -> ContextDocument:
        result = await self.session.execute(
            select(ContextDocument).where(
                ContextDocument.scope == scope,
                ContextDocument.type == type,
                ContextDocument.owner_id == owner_id,
            )
        )
        doc = result.scalar_one_or_none()
        if doc is None:
            doc = ContextDocument(scope=scope, type=type, owner_id=owner_id, content=content)
            self.session.add(doc)
        else:
            doc.content = content
        await self.session.flush()
        return doc

    async def list_for_owner(self, scope: str, owner_id: uuid.UUID) -> list[ContextDocument]:
        result = await self.session.execute(
            select(ContextDocument).where(
                ContextDocument.scope == scope, ContextDocument.owner_id == owner_id
            )
        )
        return list(result.scalars().all())
