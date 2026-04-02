"""SharedMemoryService for hybrid memory architecture."""
import logging
from typing import Any, Optional, Callable, Awaitable
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.sql.shared_memory_models import Fact, Hypothesis, Relation
from app.models.schemas.shared_memory_schemas import (
    FactCreate, FactResponse,
    HypothesisCreate, HypothesisResponse,
    RelationCreate, RelationResponse,
    SharedMemoryQuery
)
from app.orchestration.shared_memory.qdrant_adapter import SharedMemoryQdrantAdapter
from app.orchestration.context_manager import ContextBudgetManager

logger = logging.getLogger(__name__)


class SharedMemoryService:
    """
    Service for managing shared memory (Facts, Hypotheses, Relations).

    Implements hybrid architecture:
    - Qdrant for vector storage and RAG retrieval
    - PostgreSQL for metadata and relations
    - Automatic contradiction detection
    """

    def __init__(
        self,
        db: AsyncSession,
        qdrant_adapter: SharedMemoryQdrantAdapter,
        context_manager: Optional[ContextBudgetManager] = None,
        embedding_fn: Optional[Callable[[str], Awaitable[list[float]]]] = None
    ):
        """
        Initialize SharedMemoryService.

        Args:
            db: SQLAlchemy async session
            qdrant_adapter: Qdrant adapter for vector operations
            context_manager: Optional context budget manager
            embedding_fn: Function to generate embeddings (text -> list[float])
        """
        self.db = db
        self.qdrant = qdrant_adapter
        self.context_manager = context_manager or ContextBudgetManager()
        self._embedding_fn = embedding_fn

    async def _get_embedding(self, text: str) -> list[float]:
        """Get embedding for text. Override or inject embedding_fn."""
        if self._embedding_fn:
            return await self._embedding_fn(text)
        # Fallback: return zero vector (will need real embedding in production)
        # Using 768 dimensions to match Gemini embeddings
        logger.warning("No embedding function configured, using zero vector")
        return [0.0] * 768

    # ========== FACT OPERATIONS ==========

    async def create_fact(
        self,
        fact_data: FactCreate,
        embedding: Optional[list[float]] = None
    ) -> FactResponse:
        """
        Create a new fact in both PostgreSQL and Qdrant.

        Also checks for potential hypothesis contradictions.
        """
        fact_id = str(uuid4())

        # Generate embedding if not provided
        if embedding is None:
            embedding = await self._get_embedding(fact_data.text)

        # Store in Qdrant
        await self.qdrant.upsert_fact(
            fact_id=fact_id,
            embedding=embedding,
            text=fact_data.text,
            confidence=fact_data.confidence,
            source_agent_id=fact_data.source_agent_id,
            execution_id=fact_data.execution_id,
            project_id=fact_data.project_id,
            tags=fact_data.tags,
            supersedes_id=fact_data.supersedes_id
        )

        # Store metadata in PostgreSQL
        fact = Fact(
            id=fact_id,
            text=fact_data.text,
            confidence=fact_data.confidence,
            source_agent_id=fact_data.source_agent_id,
            execution_id=fact_data.execution_id,
            project_id=fact_data.project_id,
            tags=fact_data.tags,
            supersedes_id=fact_data.supersedes_id,
            embedding_id=fact_id  # Same ID in Qdrant
        )
        self.db.add(fact)
        await self.db.commit()
        await self.db.refresh(fact)

        # Automatic contradiction detection (per CONTEXT)
        await self._check_contradictions(fact_id, embedding, fact_data.confidence)

        return FactResponse.model_validate(fact)

    async def _check_contradictions(
        self,
        fact_id: str,
        embedding: list[float],
        confidence: float
    ) -> None:
        """
        Check if new fact potentially contradicts existing hypotheses.
        Links contradictions automatically (per CONTEXT decision).
        """
        similar_hypotheses = await self.qdrant.find_similar_hypotheses(
            fact_embedding=embedding,
            similarity_threshold=0.85
        )

        for hyp in similar_hypotheses:
            # If confidence differs significantly, flag as potential contradiction
            hyp_confidence = hyp.get("confidence", 0.5)
            confidence_diff = abs(confidence - hyp_confidence)

            if confidence_diff > 0.3:
                # Update hypothesis with contradicting fact
                await self._link_contradicting_fact(hyp["id"], fact_id)
                logger.info(
                    f"Linked fact {fact_id} as potential contradiction to hypothesis {hyp['id']} "
                    f"(confidence diff: {confidence_diff:.2f})"
                )

    async def _link_contradicting_fact(
        self,
        hypothesis_id: str,
        fact_id: str
    ) -> None:
        """Add fact to hypothesis's contradicting_fact_ids."""
        result = await self.db.execute(
            select(Hypothesis).where(Hypothesis.id == hypothesis_id)
        )
        hypothesis = result.scalar_one_or_none()

        if hypothesis:
            contradicting_ids = list(hypothesis.contradicting_fact_ids or [])
            if fact_id not in contradicting_ids:
                contradicting_ids.append(fact_id)
                hypothesis.contradicting_fact_ids = contradicting_ids
                await self.db.commit()

    async def get_fact(self, fact_id: str) -> Optional[FactResponse]:
        """Get fact by ID from PostgreSQL."""
        result = await self.db.execute(
            select(Fact).where(Fact.id == fact_id)
        )
        fact = result.scalar_one_or_none()
        return FactResponse.model_validate(fact) if fact else None

    # ========== HYPOTHESIS OPERATIONS ==========

    async def create_hypothesis(
        self,
        hypothesis_data: HypothesisCreate,
        embedding: Optional[list[float]] = None
    ) -> HypothesisResponse:
        """Create a new hypothesis in both PostgreSQL and Qdrant."""
        hypothesis_id = str(uuid4())

        if embedding is None:
            embedding = await self._get_embedding(hypothesis_data.text)

        # Store in Qdrant
        await self.qdrant.upsert_hypothesis(
            hypothesis_id=hypothesis_id,
            embedding=embedding,
            text=hypothesis_data.text,
            confidence=hypothesis_data.confidence,
            source_agent_id=hypothesis_data.source_agent_id,
            execution_id=hypothesis_data.execution_id,
            project_id=hypothesis_data.project_id,
            status=hypothesis_data.status
        )

        # Store in PostgreSQL
        hypothesis = Hypothesis(
            id=hypothesis_id,
            text=hypothesis_data.text,
            confidence=hypothesis_data.confidence,
            source_agent_id=hypothesis_data.source_agent_id,
            execution_id=hypothesis_data.execution_id,
            project_id=hypothesis_data.project_id,
            status=hypothesis_data.status,
            supporting_fact_ids=hypothesis_data.supporting_fact_ids,
            contradicting_fact_ids=hypothesis_data.contradicting_fact_ids
        )
        self.db.add(hypothesis)
        await self.db.commit()
        await self.db.refresh(hypothesis)

        return HypothesisResponse.model_validate(hypothesis)

    async def update_hypothesis_status(
        self,
        hypothesis_id: str,
        status: str
    ) -> Optional[HypothesisResponse]:
        """Update hypothesis status (active/confirmed/contradicted)."""
        result = await self.db.execute(
            select(Hypothesis).where(Hypothesis.id == hypothesis_id)
        )
        hypothesis = result.scalar_one_or_none()

        if hypothesis:
            hypothesis.status = status
            await self.db.commit()
            await self.db.refresh(hypothesis)

            # Update Qdrant as well
            embedding = await self._get_embedding(hypothesis.text)
            await self.qdrant.upsert_hypothesis(
                hypothesis_id=hypothesis_id,
                embedding=embedding,
                text=hypothesis.text,
                confidence=hypothesis.confidence,
                source_agent_id=hypothesis.source_agent_id,
                execution_id=hypothesis.execution_id,
                project_id=hypothesis.project_id,
                status=status
            )

            return HypothesisResponse.model_validate(hypothesis)
        return None

    # ========== RELATION OPERATIONS ==========

    async def create_relation(
        self,
        relation_data: RelationCreate
    ) -> RelationResponse:
        """Create a causal relation between facts."""
        relation = Relation(
            id=str(uuid4()),
            relation_type=relation_data.relation_type,
            source_fact_id=relation_data.source_fact_id,
            target_fact_id=relation_data.target_fact_id,
            confidence=relation_data.confidence,
            source_agent_id=relation_data.source_agent_id,
            execution_id=relation_data.execution_id,
            project_id=relation_data.project_id
        )
        self.db.add(relation)
        await self.db.commit()
        await self.db.refresh(relation)

        return RelationResponse.model_validate(relation)

    # ========== RAG RETRIEVAL ==========

    async def retrieve_context(
        self,
        query: SharedMemoryQuery,
        max_tokens: Optional[int] = None
    ) -> dict[str, Any]:
        """
        Retrieve relevant context from shared memory.

        Returns facts, hypotheses, and relations with context budget enforcement.
        Includes CONFLICT markers when contradictions exist (per CONTEXT).
        """
        # Generate query embedding
        query_embedding = await self._get_embedding(query.query_text)

        # Search facts with recency bias
        facts = await self.qdrant.search_facts(
            query_embedding=query_embedding,
            limit=query.max_items,
            min_confidence=query.min_confidence,
            agent_id=query.agent_id,
            project_id=query.project_id,
            tags=query.tags
        )

        # Search hypotheses if requested
        hypotheses = []
        if query.include_hypotheses:
            hypotheses = await self.qdrant.search_hypotheses(
                query_embedding=query_embedding,
                limit=20
            )

        # Get relations if requested (from PostgreSQL)
        relations = []
        if query.include_relations and facts:
            fact_ids = [f["id"] for f in facts[:10]]
            result = await self.db.execute(
                select(Relation).where(
                    (Relation.source_fact_id.in_(fact_ids)) |
                    (Relation.target_fact_id.in_(fact_ids))
                )
            )
            relations = [
                RelationResponse.model_validate(r).model_dump()
                for r in result.scalars().all()
            ]

        # Apply context budget if max_tokens specified
        if max_tokens:
            facts = self.context_manager.truncate_with_budget(
                items=facts,
                max_tokens=max_tokens,
                key="text"
            )

        # Mark conflicts (per CONTEXT: include BOTH with CONFLICT marker)
        for hyp in hypotheses:
            if hyp.get("contradicting_fact_ids"):
                hyp["_conflict"] = True
                hyp["_conflict_reason"] = "Has contradicting facts"

        return {
            "facts": facts,
            "hypotheses": hypotheses,
            "relations": relations,
            "query": query.query_text,
            "total_facts": len(facts),
            "total_hypotheses": len(hypotheses)
        }

    async def retrieve_cross_project_context(
        self,
        query: SharedMemoryQuery,
        current_project_id: str,
        max_tokens: Optional[int] = None
    ) -> dict[str, Any]:
        """
        Retrieve relevant context from OTHER projects.

        Finds similar patterns, learnings, and hypotheses from
        different projects that may be relevant to current work.
        This is a key capability for knowledge transfer between projects.

        Args:
            query: The semantic search query parameters
            current_project_id: Project ID to exclude from results
            max_tokens: Optional token budget for context truncation

        Returns:
            Dict with cross-project facts grouped by source project
        """
        query_embedding = await self._get_embedding(query.query_text)

        # Search facts from other projects
        cross_project_facts = await self.qdrant.search_facts_cross_project(
            query_embedding=query_embedding,
            exclude_project_id=current_project_id,
            limit=min(query.max_items, 30),  # Cap at 30 for cross-project
            min_confidence=max(query.min_confidence, 0.5)  # Higher threshold for cross-project
        )

        # Apply context budget if specified
        if max_tokens:
            cross_project_facts = self.context_manager.truncate_with_budget(
                items=cross_project_facts,
                max_tokens=max_tokens,
                key="text"
            )

        # Group by project for clarity
        by_project: dict[str, list] = {}
        for fact in cross_project_facts:
            proj_id = fact.get("project_id", "unknown")
            if proj_id not in by_project:
                by_project[proj_id] = []
            by_project[proj_id].append(fact)

        return {
            "facts": cross_project_facts,
            "by_project": by_project,
            "total_projects": len(by_project),
            "total_facts": len(cross_project_facts),
            "query": query.query_text,
            "excluded_project": current_project_id
        }
