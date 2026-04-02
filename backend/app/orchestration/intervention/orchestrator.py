"""Intervention orchestrator for autonomous capability building.

Refactored to use Gap Plan approach:
- Creates fixed gap list at start (no re-analysis during build)
- Works through gaps sequentially via GapPlanExecutor
- Only re-assesses at END of cycle
- Max 3 cycles instead of 5 iterations per gap
"""
import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Callable, Awaitable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schemas.analysis_schemas import (
    CapabilityAssessment, CapabilityGap, ConfidenceLevel, GapSeverity,
    GapType, ChallengeAnalysisRequest
)
from app.models.schemas.intervention_schemas import BuildResult, InterventionResponse
from app.models.sql.intervention_models import BlockedChallenge, ChallengeStatus
from app.models.sql.gap_plan_models import GapPlanStatus
from app.orchestration.intervention.queue_manager import BlockedChallengeQueue
from app.orchestration.intervention.capability_builder import CapabilityBuilder
from app.orchestration.intervention.injector import CapabilityInjector
from app.orchestration.intervention.retry_strategy import RetryStrategy, ApproachSelector
from app.orchestration.intervention.gap_plan_executor import GapPlanExecutor
from app.orchestration.analysis.orchestrator import PreExecutionOrchestrator
from app.services.gap_plan_service import GapPlanService
from app.services.agent_prompt_improver import AgentPromptImprover
from app.services.gap_verification_service import GapVerificationService

logger = logging.getLogger(__name__)

# Max cycles for gap resolution (3 instead of 5 iterations)
MAX_CYCLES = 3


class InterventionOrchestrator:
    """
    Orchestrates full intervention lifecycle for blocked challenges.

    REFACTORED: Now uses Gap Plan approach:
    - Creates fixed gap list at start (no re-analysis during build)
    - Works through gaps sequentially via GapPlanExecutor
    - Only re-assesses at END of cycle
    - Max 3 cycles instead of endless iterations

    Per CONTEXT decisions:
    - Fully autonomous - Developer Team works without user approval
    - Build highest-severity gaps first (Critical -> Important -> Minor)
    - Build all gaps in plan, then re-assess once (not after each build)
    - Re-run Phase 9 analysis before attempting execution (verify CAN_DO status)
    - If still MAYBE/CANNOT_DO after building: create new cycle (max 3)
    - Always notify user when challenge finally executes after capability building
    """

    def __init__(
        self,
        queue_manager: BlockedChallengeQueue,
        capability_builder: CapabilityBuilder,
        injector: CapabilityInjector,
        pre_execution_orchestrator: PreExecutionOrchestrator,
        gap_plan_service: GapPlanService,
        gap_plan_executor: GapPlanExecutor,
        db: AsyncSession,
        notify_fn: Optional[Callable[[dict], Awaitable[None]]] = None
    ):
        """
        Initialize intervention orchestrator.

        Args:
            queue_manager: BlockedChallengeQueue for challenge CRUD
            capability_builder: CapabilityBuilder for gap closure
            injector: CapabilityInjector for topology updates
            pre_execution_orchestrator: PreExecutionOrchestrator for re-assessment
            gap_plan_service: Service for gap plan CRUD
            gap_plan_executor: Executor for gap plans
            db: Database session
            notify_fn: Optional async function to send user notifications
        """
        self.queue = queue_manager
        self.builder = capability_builder
        self.injector = injector
        self.analyzer = pre_execution_orchestrator
        self.plan_service = gap_plan_service
        self.plan_executor = gap_plan_executor
        self.verifier = GapVerificationService(db)  # NEW: Verification instead of re-analysis
        self.db = db
        self._notify_fn = notify_fn

    async def process_blocked_challenge(
        self,
        challenge: BlockedChallenge
    ) -> InterventionResponse:
        """
        Process a blocked challenge through intervention lifecycle.

        REFACTORED: Uses Gap Plan approach:
        1. Get or create gap plan (fixed gap list)
        2. Execute plan via GapPlanExecutor (no re-analysis during build)
        3. Re-assess ONLY at end of cycle
        4. If CAN_DO: resolve
        5. If not CAN_DO: create new cycle (up to MAX_CYCLES)

        Args:
            challenge: BlockedChallenge to process

        Returns:
            InterventionResponse with status and built capabilities
        """
        logger.info(
            f"Processing blocked challenge: id={challenge.id[:8]}..., "
            f"attempt={challenge.attempt_number}/{challenge.max_attempts}"
        )

        # Mark as building
        await self.queue.mark_building(challenge.id)

        # Track all built results across cycles
        all_built_results: list[BuildResult] = []
        all_built_artifact_ids: list[str] = []

        # Check if we have an active plan for this challenge
        active_plan = await self.plan_service.get_active_plan(challenge.id)

        if active_plan:
            # Resume existing plan
            logger.info(
                f"Resuming existing gap plan: {active_plan.id[:8]}..., "
                f"cycle={active_plan.cycle_number}, "
                f"progress={active_plan.completed_gaps}/{active_plan.total_gaps}"
            )
        else:
            # Create new gap plan from initial assessment
            should_create, cycle_number = await self.plan_service.should_create_new_cycle(
                challenge.id, max_cycles=MAX_CYCLES
            )

            if not should_create:
                # Max cycles reached or active plan exists
                logger.warning(
                    f"Cannot create new cycle for challenge {challenge.id[:8]}..., "
                    f"max_cycles={MAX_CYCLES} reached or active plan exists"
                )

                await self._handle_max_attempts_reached(
                    challenge, [], "Max cycles reached for gap resolution"
                )

                return InterventionResponse(
                    challenge_id=challenge.id,
                    status=ChallengeStatus.FAILED,
                    route_decision="failed",
                    built_capabilities=[],
                    attempt_number=challenge.attempt_number,
                    message=f"Failed: Max {MAX_CYCLES} cycles reached for gap resolution"
                )

            # Create gap plan from challenge's gaps snapshot
            gaps = [
                CapabilityGap(**g) for g in (challenge.gaps_snapshot or [])
            ]

            if not gaps:
                logger.warning(f"No gaps in challenge snapshot: {challenge.id[:8]}...")
                return InterventionResponse(
                    challenge_id=challenge.id,
                    status=ChallengeStatus.QUEUED,
                    route_decision="no_gaps",
                    built_capabilities=[],
                    attempt_number=challenge.attempt_number,
                    message="No gaps found in challenge snapshot"
                )

            active_plan = await self.plan_service.create_plan(
                challenge_id=challenge.id,
                gaps=gaps,
                execution_id=challenge.execution_id,
                cycle_number=cycle_number
            )

            logger.info(
                f"Created gap plan: {active_plan.id[:8]}..., "
                f"cycle={cycle_number}, gaps={len(gaps)}"
            )

        # Execute the gap plan (no re-analysis during execution!)
        cycle_results, cycle_artifacts = await self.plan_executor.execute_plan(
            plan_id=active_plan.id,
            challenge_text=challenge.challenge_text,
            attempt_number=challenge.attempt_number,
            previous_failures=list(challenge.failure_reasons or [])
        )

        all_built_results.extend(cycle_results)
        all_built_artifact_ids.extend(cycle_artifacts)

        # VERIFICATION instead of Re-Analysis (no LLM call!)
        # This prevents the LLM from "discovering" new gaps each time
        logger.info(
            f"Verifying gap closure after cycle {active_plan.cycle_number}, "
            f"built {len(cycle_artifacts)} capabilities"
        )

        verification_result = await self.verifier.verify_plan_completion(active_plan.id)

        logger.info(
            f"Verification result: closed={verification_result.closed_count}/{verification_result.total_gaps}, "
            f"all_closed={verification_result.all_closed}"
        )

        # Check if all gaps are now closed
        if verification_result.all_closed:
            # Success! All original gaps are fulfilled
            await self.queue.mark_built(challenge.id, all_built_artifact_ids)
            await self.queue.mark_resolved(challenge.id)

            # Notify user
            await self._notify_user_resolved(challenge, all_built_artifact_ids)

            logger.info(
                f"Challenge RESOLVED after cycle {active_plan.cycle_number}: "
                f"{challenge.id[:8]}... (all {verification_result.total_gaps} gaps closed)"
            )

            return InterventionResponse(
                challenge_id=challenge.id,
                status=ChallengeStatus.RESOLVED,
                route_decision="execute",
                built_capabilities=all_built_results,
                attempt_number=challenge.attempt_number,
                message=f"Challenge resolved after {active_plan.cycle_number} cycle(s). "
                        f"All {verification_result.total_gaps} gaps closed. Ready for execution."
            )

        # Still have open gaps - check if we can create a new cycle
        open_gaps = verification_result.open_gaps
        if open_gaps and active_plan.cycle_number < MAX_CYCLES:
            # Create new cycle with ONLY the remaining open gaps (not new ones!)
            # Convert open gap dicts back to CapabilityGap objects
            remaining_gaps = []
            for gap in open_gaps:
                try:
                    remaining_gaps.append(CapabilityGap(
                        gap_type=GapType(gap.get("gap_type", "missing_skill")),
                        affected_capability=gap.get("affected_capability", ""),
                        severity=GapSeverity(gap.get("severity", "important")),
                        description=gap.get("description", ""),
                    ))
                except Exception as e:
                    logger.warning(f"Could not convert gap: {e}")

            if remaining_gaps:
                new_plan = await self.plan_service.create_plan(
                    challenge_id=challenge.id,
                    gaps=remaining_gaps,
                    execution_id=challenge.execution_id,
                    cycle_number=active_plan.cycle_number + 1
                )

                logger.info(
                    f"Created new cycle {new_plan.cycle_number} with {len(remaining_gaps)} REMAINING gaps "
                    f"(not new ones!) for challenge {challenge.id[:8]}..."
                )

                # Mark as built with current artifacts
                await self.queue.mark_built(challenge.id, all_built_artifact_ids)

                return InterventionResponse(
                    challenge_id=challenge.id,
                    status=ChallengeStatus.QUEUED,
                    route_decision="new_cycle",
                    built_capabilities=all_built_results,
                    attempt_number=challenge.attempt_number,
                    message=f"Cycle {active_plan.cycle_number} complete ({verification_result.closed_count} closed), "
                            f"cycle {new_plan.cycle_number} will retry {len(remaining_gaps)} remaining gaps"
                )

        # Max cycles reached or no more gaps to try
        await self.queue.mark_built(challenge.id, all_built_artifact_ids)

        failure_msg = (
            f"Still {verification_result.open_count} open gaps after {active_plan.cycle_number} cycle(s). "
            f"Built {len(all_built_artifact_ids)} capabilities, closed {verification_result.closed_count}/{verification_result.total_gaps}."
        )

        if active_plan.cycle_number >= MAX_CYCLES:
            failure_msg += f" Max cycles ({MAX_CYCLES}) reached."

        logger.warning(failure_msg)

        more_attempts = await self.queue.increment_attempt(
            challenge.id,
            failure_msg
        )

        if not more_attempts:
            # Max attempts reached
            await self._handle_max_attempts_reached(
                challenge, all_built_artifact_ids, failure_msg
            )
            return InterventionResponse(
                challenge_id=challenge.id,
                status=ChallengeStatus.FAILED,
                route_decision="failed",
                built_capabilities=all_built_results,
                attempt_number=challenge.max_attempts,
                message=f"Failed after {challenge.max_attempts} attempts, {active_plan.cycle_number} cycles"
            )

        # More attempts available
        return InterventionResponse(
            challenge_id=challenge.id,
            status=ChallengeStatus.QUEUED,
            route_decision="still_blocked",
            built_capabilities=all_built_results,
            attempt_number=challenge.attempt_number + 1,
            message=f"Still blocked after {active_plan.cycle_number} cycles, will retry"
        )

    def _sort_gaps_by_severity(
        self,
        gaps: list[CapabilityGap]
    ) -> list[CapabilityGap]:
        """
        Sort gaps by severity: Critical -> Important -> Minor.

        Per CONTEXT: Build highest-severity gaps first.
        """
        severity_order = {
            GapSeverity.CRITICAL: 0,
            GapSeverity.IMPORTANT: 1,
            GapSeverity.MINOR: 2
        }
        return sorted(gaps, key=lambda g: severity_order.get(g.severity, 99))

    def _normalize_capability_name(self, name: str) -> str:
        """
        Normalize capability name for robust deduplication.

        Handles variations like:
        - "risk assessment (downtime costs)" vs "risk assessment (downtime cost)"
        - "Cost Analysis" vs "cost_analysis"
        - "compliance assessment (DSGVO, BaFin)" vs "compliance_assessment"

        Returns a normalized key that matches semantically similar capabilities.
        """
        # Lowercase
        normalized = name.lower().strip()

        # Remove content in parentheses (details like "downtime costs", "DSGVO, BaFin")
        normalized = re.sub(r'\s*\([^)]*\)', '', normalized)

        # Replace underscores and hyphens with spaces
        normalized = normalized.replace('_', ' ').replace('-', ' ')

        # Remove extra whitespace
        normalized = ' '.join(normalized.split())

        # Remove trailing 's' for simple plural handling (but not for words like "analysis")
        words = normalized.split()
        normalized_words = []
        for word in words:
            # Don't de-pluralize words ending in 'sis', 'ss', or short words
            if len(word) > 4 and word.endswith('s') and not word.endswith(('sis', 'ss', 'us')):
                normalized_words.append(word[:-1])
            else:
                normalized_words.append(word)
        normalized = ' '.join(normalized_words)

        return normalized

    async def _handle_max_attempts_reached(
        self,
        challenge: BlockedChallenge,
        built_artifact_ids: list[str],
        final_failure: str
    ) -> None:
        """
        Handle challenge that failed after max attempts.

        Per RESEARCH pitfall 4: Deactivate provisional capabilities.
        """
        # Deactivate provisional capabilities to prevent pollution
        # Query the artifacts to determine types
        for artifact_id in built_artifact_ids:
            # Try to find the type
            artifact_type = await self._determine_artifact_type(artifact_id)
            if artifact_type:
                await self.builder.deactivate_provisional(artifact_type, artifact_id)

        # Notify user
        await self._notify_user_failed(challenge, final_failure)

    async def _determine_artifact_type(self, artifact_id: str) -> Optional[str]:
        """Determine artifact type by querying each table."""
        from sqlalchemy import select
        from app.models.sql.versioned_models import Skill, Prompt, Agent

        result = await self.db.execute(
            select(Skill).where(Skill.id == artifact_id)
        )
        if result.scalar_one_or_none():
            return "skill"

        result = await self.db.execute(
            select(Prompt).where(Prompt.id == artifact_id)
        )
        if result.scalar_one_or_none():
            return "prompt"

        result = await self.db.execute(
            select(Agent).where(Agent.id == artifact_id)
        )
        if result.scalar_one_or_none():
            return "agent"

        return None

    async def _notify_user_resolved(
        self,
        challenge: BlockedChallenge,
        built_artifact_ids: list[str]
    ) -> None:
        """
        Notify user when challenge resolved.

        Per CONTEXT: Always notify user when challenge finally executes.
        """
        notification = RetryStrategy.format_user_notification(
            challenge_id=challenge.id,
            attempt_number=challenge.attempt_number,
            success=True,
            message=f"Built {len(built_artifact_ids)} capabilities",
            built_capabilities=built_artifact_ids
        )

        logger.info(
            f"USER_NOTIFICATION: Challenge {challenge.id[:8]}... RESOLVED "
            f"after {challenge.attempt_number} attempts"
        )

        if self._notify_fn:
            await self._notify_fn(notification)

    async def _notify_user_failed(
        self,
        challenge: BlockedChallenge,
        final_failure: str
    ) -> None:
        """Notify user when challenge fails after max attempts."""
        notification = RetryStrategy.format_user_notification(
            challenge_id=challenge.id,
            attempt_number=challenge.attempt_number,
            success=False,
            message=final_failure,
            built_capabilities=[]
        )

        logger.warning(
            f"USER_NOTIFICATION: Challenge {challenge.id[:8]}... FAILED "
            f"after {challenge.max_attempts} attempts: {final_failure}"
        )

        if self._notify_fn:
            await self._notify_fn(notification)

    async def run_intervention_loop(
        self,
        poll_interval_seconds: float = 5.0
    ) -> None:
        """
        Main intervention loop - processes queued challenges continuously.

        Per CONTEXT: Fully autonomous - runs without user approval.

        This should be run as a background task.

        Args:
            poll_interval_seconds: Time to wait between queue checks
        """
        logger.info("Starting intervention loop...")

        while True:
            try:
                # Get next queued challenge
                challenge = await self.queue.get_next_queued()

                if challenge:
                    # Process with retry wait if needed
                    if challenge.attempt_number > 1:
                        # Wait before retry (per retry strategy)
                        await RetryStrategy.wait_before_retry(
                            challenge.attempt_number - 1
                        )

                    response = await self.process_blocked_challenge(challenge)

                    logger.info(
                        f"Challenge processed: id={challenge.id[:8]}..., "
                        f"status={response.status.value}, "
                        f"route={response.route_decision}"
                    )
                else:
                    # No challenges queued - wait before checking again
                    await asyncio.sleep(poll_interval_seconds)

            except Exception as e:
                logger.error(f"Intervention loop error: {e}", exc_info=True)
                # Back off on error
                await asyncio.sleep(poll_interval_seconds * 2)

    async def process_single_challenge(
        self,
        challenge_id: str
    ) -> Optional[InterventionResponse]:
        """
        Process a specific challenge by ID.

        Useful for manual intervention or testing.

        Args:
            challenge_id: ID of challenge to process

        Returns:
            InterventionResponse or None if not found
        """
        challenge = await self.queue.get_by_id(challenge_id)
        if not challenge:
            logger.warning(f"Challenge not found: {challenge_id}")
            return None

        return await self.process_blocked_challenge(challenge)


async def create_intervention_orchestrator(
    db: AsyncSession,
    llm_fn: Optional[Callable[[list[dict], dict], Awaitable[str]]] = None,
    embedding_fn: Optional[Callable[[str], Awaitable[list[float]]]] = None,
    notify_fn: Optional[Callable[[dict], Awaitable[None]]] = None
) -> InterventionOrchestrator:
    """
    Factory function to create fully-wired InterventionOrchestrator.

    Creates all dependencies (TopologyLoader, SharedMemory, DeveloperTeam, etc.)
    and wires them together.

    REFACTORED: Now includes GapPlanService, AgentPromptImprover, and GapPlanExecutor.

    Args:
        db: Database session
        llm_fn: Async LLM function
        embedding_fn: Async embedding function
        notify_fn: Async notification function

    Returns:
        Fully configured InterventionOrchestrator
    """
    import os

    from app.core.llm_client import LLMClient
    from app.orchestration.topology.loader import TopologyLoader
    from app.orchestration.shared_memory.service import SharedMemoryService
    from app.orchestration.shared_memory.qdrant_adapter import SharedMemoryQdrantAdapter
    from app.orchestration.context_manager import ContextBudgetManager
    from app.orchestration.analysis.orchestrator import PreExecutionOrchestrator
    from app.services.developer_team_orchestrator import DeveloperTeamOrchestrator
    from app.services.agent_spawner_service import AgentSpawnerService
    from app.services.runtime_agent_registry import RuntimeAgentRegistry
    from qdrant_client import QdrantClient

    # Create LLM client
    llm_client = LLMClient()

    # Create Qdrant adapter
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    qdrant_client = QdrantClient(url=qdrant_url)
    qdrant_adapter = SharedMemoryQdrantAdapter(qdrant_client)
    await qdrant_adapter.ensure_collections()

    # Create services
    topology_loader = TopologyLoader(db)
    await topology_loader.load()

    shared_memory = SharedMemoryService(
        db=db,
        qdrant_adapter=qdrant_adapter,
        context_manager=ContextBudgetManager(),
        embedding_fn=embedding_fn
    )

    # Create Developer Team components
    registry = RuntimeAgentRegistry(max_concurrent_agents=5)
    spawner = AgentSpawnerService(registry, llm_client)
    developer_team = DeveloperTeamOrchestrator(
        spawner=spawner,
        llm_client=llm_client,
        registry=registry
    )

    # Create Pre-Execution Orchestrator
    pre_execution = PreExecutionOrchestrator(
        topology_loader=topology_loader,
        shared_memory=shared_memory,
        llm_fn=llm_fn,
        embedding_fn=embedding_fn
    )

    # Create Intervention components
    queue_manager = BlockedChallengeQueue(db)
    capability_builder = CapabilityBuilder(developer_team, db)
    injector = CapabilityInjector(topology_loader, db)

    # Create Gap Plan components (new)
    gap_plan_service = GapPlanService(db)

    # Create LLM wrapper for AgentPromptImprover
    async def llm_wrapper(messages: list[dict]) -> str:
        if llm_fn:
            return await llm_fn(messages, {})
        return ""

    prompt_improver = AgentPromptImprover(db, llm_fn=llm_wrapper)

    gap_plan_executor = GapPlanExecutor(
        gap_plan_service=gap_plan_service,
        capability_builder=capability_builder,
        prompt_improver=prompt_improver,
        injector=injector,
        db=db
    )

    return InterventionOrchestrator(
        queue_manager=queue_manager,
        capability_builder=capability_builder,
        injector=injector,
        pre_execution_orchestrator=pre_execution,
        gap_plan_service=gap_plan_service,
        gap_plan_executor=gap_plan_executor,
        db=db,
        notify_fn=notify_fn
    )
