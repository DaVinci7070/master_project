"""Qdrant adapter for shared memory collections (Facts, Hypotheses)."""
import logging
import math
from datetime import datetime, timezone
from typing import Any, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, Range, MatchValue,
    PayloadSchemaType
)

logger = logging.getLogger(__name__)

# Collection names
FACTS_COLLECTION = "shared_memory_facts"
HYPOTHESES_COLLECTION = "shared_memory_hypotheses"

# Vector dimensions (Gemini text-embedding-004)
VECTOR_SIZE = 768


class SharedMemoryQdrantAdapter:
    """Qdrant adapter for shared memory storage and retrieval."""

    def __init__(self, client: QdrantClient):
        """Initialize with Qdrant client."""
        self.client = client

    async def ensure_collections(self) -> None:
        """Create collections if they don't exist."""
        for collection_name in [FACTS_COLLECTION, HYPOTHESES_COLLECTION]:
            if not self.client.collection_exists(collection_name):
                self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(
                        size=VECTOR_SIZE,
                        distance=Distance.COSINE
                    )
                )
                # Create indexes for filtering
                self._create_indexes(collection_name)
                logger.info(f"Created collection: {collection_name}")

    def _create_indexes(self, collection_name: str) -> None:
        """Create payload indexes for efficient filtering."""
        indexes = [
            ("source_agent_id", PayloadSchemaType.KEYWORD),
            ("execution_id", PayloadSchemaType.KEYWORD),
            ("project_id", PayloadSchemaType.KEYWORD),
            ("created_at_ts", PayloadSchemaType.FLOAT),
            ("confidence", PayloadSchemaType.FLOAT),
            ("tags", PayloadSchemaType.KEYWORD),
        ]
        for field_name, field_type in indexes:
            try:
                self.client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=field_type
                )
            except Exception as e:
                # Index may already exist
                logger.debug(f"Index creation skipped for {field_name}: {e}")

    async def upsert_fact(
        self,
        fact_id: str,
        embedding: list[float],
        text: str,
        confidence: float,
        source_agent_id: str,
        execution_id: str,
        project_id: str,
        tags: list[str],
        supersedes_id: Optional[str] = None
    ) -> str:
        """
        Upsert a fact to Qdrant.

        Returns:
            The point ID (same as fact_id)
        """
        now = datetime.now(timezone.utc)
        point = PointStruct(
            id=fact_id,
            vector=embedding,
            payload={
                "text": text,
                "confidence": confidence,
                "source_agent_id": source_agent_id,
                "execution_id": execution_id,
                "project_id": project_id,
                "created_at": now.isoformat(),
                "created_at_ts": now.timestamp(),
                "tags": tags,
                "supersedes_id": supersedes_id,
                "type": "fact"
            }
        )
        self.client.upsert(
            collection_name=FACTS_COLLECTION,
            points=[point],
            wait=True  # Ensure indexing completes (per RESEARCH pitfall 7)
        )
        return fact_id

    async def upsert_hypothesis(
        self,
        hypothesis_id: str,
        embedding: list[float],
        text: str,
        confidence: float,
        source_agent_id: str,
        execution_id: str,
        project_id: str,
        status: str = "active"
    ) -> str:
        """Upsert a hypothesis to Qdrant."""
        now = datetime.now(timezone.utc)
        point = PointStruct(
            id=hypothesis_id,
            vector=embedding,
            payload={
                "text": text,
                "confidence": confidence,
                "source_agent_id": source_agent_id,
                "execution_id": execution_id,
                "project_id": project_id,
                "created_at": now.isoformat(),
                "created_at_ts": now.timestamp(),
                "status": status,
                "type": "hypothesis"
            }
        )
        self.client.upsert(
            collection_name=HYPOTHESES_COLLECTION,
            points=[point],
            wait=True
        )
        return hypothesis_id

    async def search_facts(
        self,
        query_embedding: list[float],
        limit: int = 50,
        min_confidence: float = 0.0,
        agent_id: Optional[str] = None,
        project_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
        recency_scale: int = 604800  # 1 week in seconds
    ) -> list[dict[str, Any]]:
        """
        Search facts with semantic similarity + recency bias.

        Args:
            query_embedding: Query vector
            limit: Max results (soft max from CONTEXT)
            min_confidence: Minimum confidence filter
            agent_id: Filter by source agent
            project_id: Filter by project (optional)
            tags: Filter by tags (any match)
            recency_scale: Decay scale in seconds (default 1 week)

        Returns:
            List of fact dicts with scores
        """
        # Build filter conditions
        must_conditions = []
        if min_confidence > 0:
            must_conditions.append(
                FieldCondition(key="confidence", range=Range(gte=min_confidence))
            )
        if agent_id:
            must_conditions.append(
                FieldCondition(key="source_agent_id", match=MatchValue(value=agent_id))
            )
        if project_id:
            must_conditions.append(
                FieldCondition(key="project_id", match=MatchValue(value=project_id))
            )

        query_filter = Filter(must=must_conditions) if must_conditions else None

        # Search with recency scoring using query_points (qdrant-client 1.7+)
        results = self.client.query_points(
            collection_name=FACTS_COLLECTION,
            query=query_embedding,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
            score_threshold=0.0
        ).points

        # Apply recency boost in post-processing
        # (Alternative to Qdrant native decay until upgrade)
        now_ts = datetime.now(timezone.utc).timestamp()
        boosted_results = []
        for hit in results:
            payload = hit.payload or {}
            created_ts = payload.get("created_at_ts", now_ts)
            age_seconds = now_ts - created_ts
            # Exponential decay: e^(-age/scale)
            recency_boost = math.exp(-age_seconds / recency_scale)
            combined_score = hit.score * 0.7 + recency_boost * 0.3

            boosted_results.append({
                "id": str(hit.id),
                "score": combined_score,
                "semantic_score": hit.score,
                "recency_boost": recency_boost,
                **payload
            })

        # Re-sort by combined score
        boosted_results.sort(key=lambda x: x["score"], reverse=True)
        return boosted_results

    async def search_hypotheses(
        self,
        query_embedding: list[float],
        limit: int = 20,
        status: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Search hypotheses with optional status filter."""
        conditions = []
        if status:
            conditions.append(
                FieldCondition(key="status", match=MatchValue(value=status))
            )

        query_filter = Filter(must=conditions) if conditions else None

        results = self.client.query_points(
            collection_name=HYPOTHESES_COLLECTION,
            query=query_embedding,
            query_filter=query_filter,
            limit=limit,
            with_payload=True
        ).points

        return [
            {"id": str(hit.id), "score": hit.score, **(hit.payload or {})}
            for hit in results
        ]

    async def find_similar_hypotheses(
        self,
        fact_embedding: list[float],
        similarity_threshold: float = 0.85
    ) -> list[dict[str, Any]]:
        """
        Find hypotheses that may be contradicted by a new fact.
        Used for automatic contradiction detection (per CONTEXT).

        Returns hypotheses with high semantic similarity to the fact.
        """
        results = self.client.query_points(
            collection_name=HYPOTHESES_COLLECTION,
            query=fact_embedding,
            query_filter=Filter(
                must=[FieldCondition(key="status", match=MatchValue(value="active"))]
            ),
            limit=10,
            score_threshold=similarity_threshold,
            with_payload=True
        ).points

        return [
            {"id": str(hit.id), "score": hit.score, **(hit.payload or {})}
            for hit in results
        ]

    async def search_facts_cross_project(
        self,
        query_embedding: list[float],
        exclude_project_id: str,
        limit: int = 30,
        min_confidence: float = 0.5,
        recency_scale: int = 2592000  # 30 days for cross-project
    ) -> list[dict[str, Any]]:
        """
        Search facts from OTHER projects (excluding current project).

        Used for cross-project pattern retrieval to find similar patterns,
        learnings, and hypotheses from different projects that may be
        relevant to current work.

        Args:
            query_embedding: Query vector
            exclude_project_id: Project ID to exclude from results
            limit: Max results (default 30 for cross-project)
            min_confidence: Minimum confidence filter (default 0.5 for quality)
            recency_scale: Decay scale in seconds (30 days - longer for cross-project)

        Returns:
            List of fact dicts with scores, sorted by combined score
        """
        # Build filter to EXCLUDE current project
        must_not_conditions = [
            FieldCondition(key="project_id", match=MatchValue(value=exclude_project_id))
        ]
        must_conditions = [
            FieldCondition(key="confidence", range=Range(gte=min_confidence))
        ]

        query_filter = Filter(
            must=must_conditions,
            must_not=must_not_conditions
        )

        # Search with lower threshold for cross-project (patterns may be less similar)
        results = self.client.query_points(
            collection_name=FACTS_COLLECTION,
            query=query_embedding,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
            score_threshold=0.6  # Lower threshold for cross-project
        ).points

        # Apply recency boost with longer scale for cross-project patterns
        now_ts = datetime.now(timezone.utc).timestamp()
        boosted_results = []
        for hit in results:
            payload = hit.payload or {}
            created_ts = payload.get("created_at_ts", now_ts)
            age_seconds = now_ts - created_ts
            # Exponential decay with longer scale for cross-project
            recency_boost = math.exp(-age_seconds / recency_scale)
            combined_score = hit.score * 0.7 + recency_boost * 0.3

            boosted_results.append({
                "id": str(hit.id),
                "score": combined_score,
                "semantic_score": hit.score,
                "recency_boost": recency_boost,
                "project_id": payload.get("project_id"),
                **payload
            })

        # Re-sort by combined score
        boosted_results.sort(key=lambda x: x["score"], reverse=True)
        return boosted_results
