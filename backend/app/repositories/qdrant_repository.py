from __future__ import annotations

import os
import hashlib
import uuid
import json
import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from qdrant_client import QdrantClient, models
from qdrant_client.models import Filter, FieldCondition, MatchAny, Range
from functools import lru_cache
from app.adapters.qdrant.reports_ports import ReportsIndex
from app.adapters.qdrant.templates_port import TemplatesIndex
from app.models.qdrant.qdrant_models import ReportRecord, UpsertBatchResult, SearchHit, TemplateHit, TemplateRecord
from app.core.security import hash_user_id

log = logging.getLogger("qdrant-reports-store")

class QdrantReportsRepository(ReportsIndex, TemplatesIndex):
    def __init__(
            self,
            *,
            qdrant_url: str,
            api_key: Optional[str] = None,
            prefer_grpc: bool = False,
            embed_model_name: str,
            collection_prefix: str = "reports",
            template_collection_prefix: str = "templates",
    ) -> None:
        self.embed_model_name = embed_model_name
        self.collection_prefix = collection_prefix
        self.template_collection_prefix = template_collection_prefix

        self.client = QdrantClient(
            url=qdrant_url,
            api_key=api_key,
            prefer_grpc=prefer_grpc,
        )

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _make_snippet(text: str, max_len: int = 320) -> str:
        t = " ".join(text.split())
        return (t[: max_len - 1] + "…") if len(t) > max_len else t

    def user_collection_name(self, user_id: str) -> str:
        normalized = (user_id or "").strip()
        if not normalized:
            raise ValueError("user_id darf nicht leer sein")

        digest = hash_user_id(normalized)
        collection_name = f"{self.collection_prefix}__{digest}"

        log.debug(f"Collection name for user_id '{normalized}': {collection_name}")
        return collection_name

    def user_template_collection_name(self, user_id: str) -> str:
        normalized = (user_id or "").strip()
        if not normalized:
            raise ValueError("user_id darf nicht leer sein")
        digest = hash_user_id(normalized)
        return f"{self.template_collection_prefix}__{digest}"

    def ensure_user_template_collection(self, user_id: str) -> str:
        cname = self.user_template_collection_name(user_id)

        if not self.client.collection_exists(cname):
            vec_size = self.client.get_embedding_size(self.embed_model_name)
            self.client.create_collection(
                collection_name=cname,
                vectors_config=models.VectorParams(
                    size=vec_size,
                    distance=models.Distance.COSINE,
                ),
            )
            log.info("Created TEMPLATE collection=%s size=%s model=%s", cname, vec_size, self.embed_model_name)

        return cname

    def ensure_user_collection(self, user_id: str) -> str:
        cname = self.user_collection_name(user_id)

        if not self.client.collection_exists(cname):
            vec_size = self.client.get_embedding_size(self.embed_model_name)
            self.client.create_collection(
                collection_name=cname,
                vectors_config=models.VectorParams(
                    size=vec_size,
                    distance=models.Distance.COSINE,
                ),
            )
            log.info("Created collection=%s size=%s model=%s", cname, vec_size, self.embed_model_name)

        return cname

    def _template_to_document(self, t: "TemplateRecord") -> str:
        parts: list[str] = [
            f"template_id: {t.template_id}",
            f"name: {t.name}",
        ]
        if t.description:
            parts.append(f"description: {t.description}")
        if t.tags:
            parts.append("tags: " + ", ".join([x for x in t.tags if x]))

        try:
            content_json = json.dumps(t.content or {}, ensure_ascii=False)
        except Exception:
            content_json = str(t.content)

        if len(content_json) > 4000:
            content_json = content_json[:4000] + "…"

        parts.append("content: " + content_json)
        return "\n".join(parts)

    def upsert_template(self, user_id: str, template: "TemplateRecord") -> UpsertBatchResult:

        if not user_id or not user_id.strip():
            raise ValueError("user_id darf nicht leer sein")
        if not template.template_id:
            raise ValueError("template.template_id darf nicht leer sein")
        if not template.name or not template.name.strip():
            raise ValueError("template.name darf nicht leer sein")

        cname = self.ensure_user_template_collection(user_id)

        created_at = self._now_iso()
        document = self._template_to_document(template)

        self.client.upload_collection(
            collection_name=cname,
            vectors=[models.Document(text=document, model=self.embed_model_name)],
            ids=[template.template_id],
            payload=[
                {
                    "hashed_user_id": hash_user_id(user_id),  
                    "template_id": template.template_id,
                    "name": template.name,
                    "description": template.description,
                    "content": template.content or {},  
                    "tags": template.tags or [],
                    "metadata": template.metadata or {},
                    "created_at": created_at,
                    "document": document,  
                }
            ],
            wait=True,
        )

        return UpsertBatchResult(user_collection=cname, upserted=1, ids=[template.template_id])

    def _build_template_hit(self, p: Any, include_text: bool) -> TemplateHit:
        pl = p.payload or {}
        if not isinstance(pl, dict):
            pl = {}

        doc = pl.get("document") or ""
        return TemplateHit(
            id=str(p.id),
            score=float(getattr(p, "score", 0.0) or 0.0),
            template_id=pl.get("template_id") or str(p.id),
            name=pl.get("name") or pl.get("title"),
            description=pl.get("description"),
            content=pl.get("content") if include_text else None,
            tags=pl.get("tags") or [],
            snippet=self._make_snippet(doc) if doc else None,
            metadata=pl.get("metadata") or {},
        )

    def search_templates(
        self,
        user_id: str,
        query: str,
        *,
        limit: int = 5,
        include_text: bool = True,
    ) -> list[TemplateHit]:
        cname = self.user_template_collection_name(user_id)
        if not self.client.collection_exists(cname):
            return []

        res = self.client.query_points(
            collection_name=cname,
            query=models.Document(text=query, model=self.embed_model_name),
            limit=limit,
            with_payload=True,
        ).points

        return [self._build_template_hit(p, include_text) for p in res]

    def upsert_reports_batch(self, user_id: str, reports: Iterable[ReportRecord]) -> UpsertBatchResult:
        cname = self.ensure_user_collection(user_id)

        ids: list[str] = []
        payload: list[dict[str, Any]] = []
        vectors: list[models.Document] = []

        for r in reports:
            if not r.text or not r.text.strip():
                continue

            rid = (r.report_id or "").strip() or str(uuid.uuid4())
            created_at = r.created_at or self._now_iso()

            ids.append(rid)
            vectors.append(models.Document(text=r.text, model=self.embed_model_name))
            payload.append(
                {
                    "hashed_user_id": hash_user_id(user_id),  
                    "report_id": rid,
                    "title": r.title,
                    "text": r.text,
                    "fields": r.fields or {},
                    "created_at": created_at,
                    "created_at_ts": r.created_at_ts,
                    "tags": r.tags or [],
                    "source": r.source,
                    "metadata": r.metadata or {},
                    "document": r.text,  
                }
            )

        if not ids:
            return UpsertBatchResult(user_collection=cname, upserted=0, ids=[])

        self.client.upload_collection(
            collection_name=cname,
            vectors=vectors,
            ids=ids,
            payload=payload,
            wait=True,
        )

        return UpsertBatchResult(user_collection=cname, upserted=len(ids), ids=ids)

    def _build_hit(self, p: Any, include_text: bool) -> SearchHit:
        pl = p.payload or {}
        doc = (pl.get("document") or "") if isinstance(pl, dict) else ""

        return SearchHit(
            id=str(p.id),
            score=float(p.score) if hasattr(p, 'score') else 1.0,
            report_id=pl.get("report_id"),
            title=pl.get("title"),
            text=doc if include_text else None,
            fields=pl.get("fields"),
            created_at=pl.get("created_at"),
            created_at_ts=pl.get("created_at_ts"),
            tags=pl.get("tags") or [],
            source=pl.get("source"),
            snippet=self._make_snippet(doc) if doc else None,
            metadata=pl.get("metadata") or {},
        )

    def get_template_by_id(
            self,
            user_id: str,
            template_id: str,
            include_text: bool = True,
    ) -> Optional[TemplateHit]:
        if not user_id or not user_id.strip():
            raise ValueError("user_id darf nicht leer sein")
        if not template_id or not template_id.strip():
            raise ValueError("template_id darf nicht leer sein")

        cname = self.user_template_collection_name(user_id)
        if not self.client.collection_exists(cname):
            return None

        try:
            points = self.client.retrieve(
                collection_name=cname,
                ids=[template_id],
                with_payload=True,
                with_vectors=False,
            )
            template = self._build_template_hit(points[0], include_text) if points else None
            log.info(f"Found Template hit={template}")
            return template
        except Exception as e:
            log.error("Error retrieving template %s: %s", template_id, e)
            return None

    def list_user_templates(self, user_id: str) -> list[TemplateHit]:
        cname = self.user_template_collection_name(user_id)
        if not self.client.collection_exists(cname):
            return []

        try:
            result_points = []
            offset = None
            while True:
                res = self.client.scroll(
                    collection_name=cname,
                    limit=100,
                    with_payload=True,
                    with_vectors=False,
                    offset=offset
                )
                points, next_offset = res
                result_points.extend(points)
                if next_offset is None:
                    break
                offset = next_offset

            return [self._build_template_hit(p, include_text=True) for p in result_points]

        except Exception as e:
            log.error(f"Error listing templates for user {user_id}: {e}")
            return []

    def search(
            self,
            user_id: str,
            query: str,
            *,
            limit: int = 5,
            include_text: bool = False,
    ) -> list[SearchHit]:
        cname = self.user_collection_name(user_id)
        if not self.client.collection_exists(cname):
            return []

        res = self.client.query_points(
            collection_name=cname,
            query=models.Document(text=query, model=self.embed_model_name),
            limit=limit,
            with_payload=True,
        ).points

        return [self._build_hit(p, include_text) for p in res]

    def search_by_tags(
            self,
            user_id: str,
            tags: list[str],
            *,
            limit: int = 10,
            include_text: bool = False,
    ) -> list[SearchHit]:
        cname = self.user_collection_name(user_id)
        if not self.client.collection_exists(cname):
            return []

        res = self.client.scroll(
            collection_name=cname,
            scroll_filter=Filter(
                should=[
                    FieldCondition(key="tags", match=MatchAny(any=tags))
                ]
            ),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )

        return [self._build_hit(p, include_text) for p in res[0]]

    def search_by_date_range(
            self,
            user_id: str,
            start_date: str,
            end_date: str,
            *,
            limit: int = 10,
            include_text: bool = False,
    ) -> list[SearchHit]:
        cname = self.user_collection_name(user_id)
        if not self.client.collection_exists(cname):
            return []

        start_ts = datetime.fromisoformat(start_date.replace('Z', '+00:00')).timestamp()
        end_ts = datetime.fromisoformat(end_date.replace('Z', '+00:00')).timestamp()

        res = self.client.scroll(
            collection_name=cname,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="created_at_ts",
                        range=Range(gte=start_ts, lte=end_ts)
                    )
                ]
            ),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )

        return [self._build_hit(p, include_text) for p in res[0]]

    def get_by_id(
            self,
            user_id: str,
            report_id: str,
            *,
            include_text: bool = True,
    ) -> Optional[SearchHit]:
        cname = self.user_collection_name(user_id)
        if not self.client.collection_exists(cname):
            return None

        try:
            points = self.client.retrieve(
                collection_name=cname,
                ids=[report_id],
                with_payload=True,
                with_vectors=False,
            )
            return self._build_hit(points[0], include_text) if points else None
        except Exception as e:
            log.error(f"Error retrieving report {report_id}: {e}")
            return None


    def get_user_stats(self, user_id: str) -> dict[str, Any]:
        cname = self.user_collection_name(user_id)
        if not self.client.collection_exists(cname):
            return {
                "total_documents": 0,
                "by_tag": {},
                "date_range": None,
            }

        info = self.client.get_collection(cname)
        total = info.points_count

        all_points = self.client.scroll(
            collection_name=cname,
            limit=total,
            with_payload=True,
            with_vectors=False,
        )[0]

        tag_counts: dict[str, int] = {}
        dates: list[str] = []

        for p in all_points:
            pl = p.payload or {}
            for tag in pl.get("tags") or []:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

            if created := pl.get("created_at"):
                dates.append(created)

        date_range = None
        if dates:
            dates.sort()
            date_range = {"earliest": dates[0], "latest": dates[-1]}

        return {
            "total_documents": total,
            "by_tag": tag_counts,
            "date_range": date_range,
        }

    def delete_report(self, user_id: str, report_id: str) -> bool:
        cname = self.user_collection_name(user_id)
        if not self.client.collection_exists(cname):
            return False
        try:
            self.client.delete(
                collection_name=cname,
                points_selector=models.PointIdsList(points=[report_id]),
                wait=True
            )
            return True
        except Exception as e:
            log.error(f"Error deleting report {report_id} from qdrant: {e}")
            return False

    def delete_template(self, user_id: str, template_id: str) -> bool:
        cname = self.user_template_collection_name(user_id)
        if not self.client.collection_exists(cname):
            return False
        try:
            self.client.delete(
                collection_name=cname,
                points_selector=models.PointIdsList(points=[template_id]),
                wait=True
            )
            return True
        except Exception as e:
            log.error(f"Error deleting template {template_id} from qdrant: {e}")
            return False

@lru_cache
def get_reports_store() -> ReportsIndex:
    return QdrantReportsRepository(
        qdrant_url=os.getenv("QDRANT_URL", "http://localhost:6333"),
        api_key=os.getenv("QDRANT_API_KEY"),
        prefer_grpc=os.getenv("QDRANT_PREFER_GRPC", "false").lower() == "true",
        embed_model_name=os.getenv(
            "EMBED_MODEL_NAME",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        ),
        collection_prefix=os.getenv("QDRANT_COLLECTION_PREFIX", "reports"),
        template_collection_prefix=os.getenv("QDRANT_TEMPLATE_COLLECTION_PREFIX", "templates"),
    )
