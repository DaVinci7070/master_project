"""Pre-execution analysis orchestrator."""
import logging
from datetime import datetime, timezone
from typing import Callable, Awaitable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schemas.analysis_schemas import (
    ConfidenceLevel, CapabilityAssessment,
    ChallengeAnalysisRequest, ChallengeAnalysisResponse
)
from app.models.schemas.shared_memory_schemas import FactCreate, SharedMemoryQuery
from app.orchestration.analysis.challenge_analyzer import ChallengeAnalyzer
from app.orchestration.analysis.feasibility_judge import FeasibilityJudge
from app.orchestration.analysis.gap_detector import GapDetector
from app.orchestration.topology.loader import TopologyLoader
from app.orchestration.shared_memory.service import SharedMemoryService

logger = logging.getLogger(__name__)

# Route identifiers
ROUTE_EXECUTE = "execute"
ROUTE_DEVELOPER_TEAM = "developer_team"


class PreExecutionOrchestrator:
    """
    Orchestrates pre-execution capability analysis.

    This is the main entry point for the pre-execution analysis system.
    Coordinates:
    1. ChallengeAnalyzer - extracts capabilities and matches against topology
    2. GapDetector - identifies gaps and computes confidence verdict
    3. SharedMemory - persists assessment for future reference
    4. Routing - returns autonomous routing decision

    Per CONTEXT:
    - Always automatic - every challenge is analyzed before execution
    - CANNOT_DO and MAYBE automatically route to Developer Team
    - Log all assessments for system improvement
    """

    def __init__(
        self,
        topology_loader: TopologyLoader,
        shared_memory: SharedMemoryService,
        llm_fn: Optional[Callable[[list[dict], dict], Awaitable[str]]] = None,
        embedding_fn: Optional[Callable[[str], Awaitable[list[float]]]] = None
    ):
        """
        Initialize pre-execution orchestrator.

        Args:
            topology_loader: For accessing topology capabilities
            shared_memory: For persistence and past success retrieval
            llm_fn: Async function(messages, kwargs) -> response_content
            embedding_fn: Async function(text) -> embedding vector
        """
        self.topology = topology_loader
        self.shared_memory = shared_memory
        self._llm_fn = llm_fn
        self._embedding_fn = embedding_fn

        # Initialize sub-services
        self.challenge_analyzer = ChallengeAnalyzer(
            topology_loader=topology_loader,
            shared_memory=shared_memory,
            llm_fn=llm_fn,
            embedding_fn=embedding_fn
        )
        self.feasibility_judge = FeasibilityJudge(
            llm_fn=llm_fn,
            topology_loader=topology_loader,
        )
        self.gap_detector = GapDetector(
            llm_fn=llm_fn,
            feasibility_judge=self.feasibility_judge,
        )

    async def analyze_challenge(
        self,
        request: ChallengeAnalysisRequest
    ) -> ChallengeAnalysisResponse:
        """
        Analyze a challenge and return assessment with routing decision.

        This is called BEFORE execution for every challenge.

        Args:
            request: Challenge analysis request

        Returns:
            Response with assessment and routing decision
        """
        logger.info(
            f"Pre-execution analysis starting for execution {request.execution_id}"
        )
        start_time = datetime.now(timezone.utc)

        # 1. Run challenge analysis (capability extraction + matching)
        context = await self.challenge_analyzer.analyze(
            challenge_text=request.challenge_text,
            execution_id=request.execution_id,
            project_id=request.project_id,
            include_cross_project=request.include_cross_project
        )

        # 2. Build assessment (gap detection + confidence verdict)
        assessment = await self.gap_detector.build_assessment(context)

        # 3. Persist assessment to SharedMemory immediately (per CONTEXT)
        await self._persist_assessment(
            assessment=assessment,
            challenge_text=request.challenge_text,
            execution_id=request.execution_id,
            project_id=request.project_id
        )

        # 4. Determine routing decision (per CONTEXT: autonomous)
        route_decision = self._determine_route(assessment)

        # 5. Log for system improvement (per CONTEXT)
        self._log_assessment(
            execution_id=request.execution_id,
            confidence=assessment.confidence,
            gap_count=len(assessment.gaps),
            route=route_decision,
            duration_ms=int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
        )

        # 6. Build response
        response = ChallengeAnalysisResponse(
            assessment=assessment,
            challenge_text=request.challenge_text[:500],  # Truncate for response
            execution_id=request.execution_id,
            analyzed_at=datetime.now(timezone.utc),
            route_decision=route_decision
        )

        logger.info(
            f"Pre-execution analysis complete: {assessment.confidence.value} "
            f"-> route: {route_decision}"
        )

        return response

    async def _persist_assessment(
        self,
        assessment: CapabilityAssessment,
        challenge_text: str,
        execution_id: str,
        project_id: str
    ) -> str:
        """
        Persist assessment to SharedMemory immediately.

        Per CONTEXT: Write assessments to Shared Memory as Facts immediately.
        """
        # Build fact text summarizing assessment
        gap_summary = ""
        if assessment.gaps:
            gap_types = [g.gap_type.value for g in assessment.gaps[:3]]
            gap_summary = f" Gaps: {', '.join(gap_types)}."

        fact_text = (
            f"Challenge assessment: {assessment.confidence.value}. "
            f"Factors: {', '.join(assessment.top_factors)}.{gap_summary}"
        )

        # Confidence for the fact itself (not the assessment confidence)
        # Higher confidence if we had similar past successes
        fact_confidence = 0.8 if assessment.similar_past_success else 0.7

        # Build tags for future retrieval
        tags = [
            "capability_assessment",
            f"confidence_{assessment.confidence.value.lower()}"
        ]

        # Add gap type tags for recurring gap tracking (per CONTEXT)
        for gap in assessment.gaps:
            tag = f"gap_{gap.gap_type.value}"
            if tag not in tags:
                tags.append(tag)

        # Mark as success or needs_improvement for pattern matching
        if assessment.confidence == ConfidenceLevel.CAN_DO:
            tags.append("execution_success")
        else:
            tags.append("needs_improvement")

        fact = FactCreate(
            text=fact_text,
            confidence=fact_confidence,
            source_agent_id="pre_execution_analyzer",
            execution_id=execution_id,
            project_id=project_id,
            tags=tags
        )

        try:
            result = await self.shared_memory.create_fact(fact)
            logger.debug(f"Assessment persisted as fact: {result.id}")
            return result.id
        except Exception as e:
            logger.error(f"Failed to persist assessment: {e}")
            return ""

    def _determine_route(self, assessment: CapabilityAssessment) -> str:
        """
        Determine routing based on assessment.

        Per CONTEXT:
        - CANNOT_DO: automatically routes to Developer Team (no user input)
        - MAYBE: treated like CANNOT_DO - build/address gaps before attempting
        - CAN_DO: proceed to execution
        """
        if assessment.should_route_to_developer():
            return ROUTE_DEVELOPER_TEAM
        return ROUTE_EXECUTE

    def _log_assessment(
        self,
        execution_id: str,
        confidence: ConfidenceLevel,
        gap_count: int,
        route: str,
        duration_ms: int
    ) -> None:
        """
        Log assessment for system improvement.

        Per CONTEXT: Log all assessments with challenge, verdict, gaps
        for system improvement tracking.
        """
        logger.info(
            f"ASSESSMENT_LOG execution_id={execution_id} "
            f"confidence={confidence.value} "
            f"gaps={gap_count} "
            f"route={route} "
            f"duration_ms={duration_ms}"
        )

    async def get_recurring_gaps(
        self,
        project_id: str,
        min_occurrences: int = 3
    ) -> list[dict]:
        """
        Query recurring gaps across challenges.

        Per CONTEXT: Track recurring gaps across challenges
        ("This gap has blocked 3 previous challenges")
        """
        # Search for facts with gap tags
        query = SharedMemoryQuery(
            query_text="capability gap assessment",
            project_id=project_id,
            min_confidence=0.5,
            max_items=100,
            tags=["capability_assessment"]
        )

        results = await self.shared_memory.retrieve_context(query)
        facts = results.get("facts", [])

        # Count gap occurrences by type
        gap_counts: dict[str, int] = {}
        for fact in facts:
            tags = fact.get("tags", [])
            for tag in tags:
                if tag.startswith("gap_"):
                    gap_type = tag.replace("gap_", "")
                    gap_counts[gap_type] = gap_counts.get(gap_type, 0) + 1

        # Filter to recurring gaps
        recurring = [
            {"gap_type": gap_type, "occurrences": count}
            for gap_type, count in gap_counts.items()
            if count >= min_occurrences
        ]

        # Sort by occurrence count
        recurring.sort(key=lambda x: x["occurrences"], reverse=True)

        return recurring


async def create_pre_execution_orchestrator(
    db: AsyncSession,
    llm_fn: Optional[Callable[[list[dict], dict], Awaitable[str]]] = None,
    embedding_fn: Optional[Callable[[str], Awaitable[list[float]]]] = None
) -> PreExecutionOrchestrator:
    """
    Factory function to create pre-execution orchestrator.

    Creates all required dependencies (TopologyLoader, SharedMemoryService).
    """
    import os

    from app.orchestration.topology.loader import TopologyLoader
    from app.orchestration.shared_memory.service import SharedMemoryService
    from app.orchestration.shared_memory.qdrant_adapter import SharedMemoryQdrantAdapter
    from app.orchestration.context_manager import ContextBudgetManager
    from qdrant_client import QdrantClient

    # Create Qdrant adapter
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    qdrant_client = QdrantClient(url=qdrant_url)
    qdrant_adapter = SharedMemoryQdrantAdapter(qdrant_client)
    await qdrant_adapter.ensure_collections()

    # Create services
    topology_loader = TopologyLoader(db)
    shared_memory = SharedMemoryService(
        db=db,
        qdrant_adapter=qdrant_adapter,
        context_manager=ContextBudgetManager(),
        embedding_fn=embedding_fn
    )

    return PreExecutionOrchestrator(
        topology_loader=topology_loader,
        shared_memory=shared_memory,
        llm_fn=llm_fn,
        embedding_fn=embedding_fn
    )
