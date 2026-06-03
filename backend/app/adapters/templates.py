from __future__ import annotations

import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.qdrant.reports_ports import ReportsIndex
from app.models.api.template_models import TemplateUploadRequest, TemplateUploadResponse, TemplateDetail, TemplateResponse
from app.models.qdrant.qdrant_models import TemplateRecord
from app.repositories.qdrant_repository import QdrantReportsRepository

import logging
log = logging.getLogger(__name__)

class TemplateService:
    def __init__(self, qdrant_repo: QdrantReportsRepository,) -> None:
        self.qdrant_repo = qdrant_repo

    async def get_template_or_fallback(self, user_id: str, template_id: str | None) -> str | None:
        if not template_id:
            return None

        hit = self.qdrant_repo.get_template_by_id(user_id=user_id, template_id=template_id, include_text=False)
        if hit:
            return template_id
        log.warning(f"Template {template_id} not found for user {user_id}. Falling back to default.")
        return None

    async def store_template(
        self,
        user_id: str,
        data: TemplateUploadRequest,
    ) -> TemplateUploadResponse:
        template_id = uuid.uuid4()

        record = TemplateRecord(
            user_id=user_id.strip(),
            template_id=template_id,
            name=data.name.strip(),
            description=data.description,
            content=data.content or {},
            tags=data.tags or [],
            metadata=data.metadata or {},
        )

        res = self.qdrant_repo.upsert_template(user_id=record.user_id, template=record)

        return TemplateUploadResponse(
            user_collection=res.user_collection,
            upserted=res.upserted,
            ids=[str(x) for x in res.ids],
        )

    async def get_user_templates(self, user_id: str) -> list[TemplateDetail]:
        hits = self.qdrant_repo.list_user_templates(user_id=user_id)
        return [
            TemplateDetail(
                id=h.template_id,
                name=h.name,
                description=h.description
            )
            for h in hits
        ]

    async def get_template_by_id(self, user_id: str, template_id: str) -> TemplateResponse | None:
        hit = self.qdrant_repo.get_template_by_id(user_id=user_id, template_id=template_id, include_text=True)
        if not hit:
            return None


        content = hit.content
        if not isinstance(content, dict):

            content = {}

        return TemplateResponse(
            id=hit.template_id,
            name=hit.name,
            description=hit.description,
            content=content,
            tags=hit.tags or [],
            metadata=hit.metadata or {}
        )

    async def delete_template(self, user_id: str, template_id: str) -> bool:
        return self.qdrant_repo.delete_template(user_id=user_id, template_id=template_id)
