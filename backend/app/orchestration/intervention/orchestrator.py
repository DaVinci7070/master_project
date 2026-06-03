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
from app.orchestration.execution.gap_plan import GapPlanService
from app.feedback_loop.improvement.prompt_improver import AgentPromptImprover
from app.orchestration.execution.gap_verification import GapVerificationService

logger = logging.getLogger(__name__)

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
        session_factory,
        notify_fn: Optional[Callable[[dict], Awaitable[None]]] = None
    ):
        self.queue = queue_manager
        self.builder = capability_builder
        self.injector = injector
        self.analyzer = pre_execution_orchestrator
        self.plan_service = gap_plan_service
        self.plan_executor = gap_plan_executor
        self.verifier = GapVerificationService(session_factory)
        self.session_factory = session_factory
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

        await self.queue.mark_building(challenge.id)

        all_built_results: list[BuildResult] = []
        all_built_artifact_ids: list[str] = []

        active_plan = await self.plan_service.get_active_plan(challenge.id)

        if active_plan:
            logger.info(
                f"Resuming existing gap plan: {active_plan.id[:8]}..., "
                f"cycle={active_plan.cycle_number}, "
                f"progress={active_plan.completed_gaps}/{active_plan.total_gaps}"
            )
        else:
            should_create, cycle_number = await self.plan_service.should_create_new_cycle(
                challenge.id, max_cycles=MAX_CYCLES
            )

            if not should_create:
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

        cycle_results, cycle_artifacts = await self.plan_executor.execute_plan(
            plan_id=active_plan.id,
            challenge_text=challenge.challenge_text,
            attempt_number=challenge.attempt_number,
            previous_failures=list(challenge.failure_reasons or [])
        )

        all_built_results.extend(cycle_results)
        all_built_artifact_ids.extend(cycle_artifacts)

        logger.info(
            f"Verifying gap closure after cycle {active_plan.cycle_number}, "
            f"built {len(cycle_artifacts)} capabilities"
        )

        verification_result = await self.verifier.verify_plan_completion(active_plan.id)

        logger.info(
            f"Verification result: closed={verification_result.closed_count}/{verification_result.total_gaps}, "
            f"all_closed={verification_result.all_closed}"
        )

        if verification_result.all_closed:
            await self.queue.mark_built(challenge.id, all_built_artifact_ids)
            await self.queue.mark_resolved(challenge.id)

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

        open_gaps = verification_result.open_gaps
        if open_gaps and active_plan.cycle_number < MAX_CYCLES:
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
        normalized = name.lower().strip()

        normalized = re.sub(r'\s*\([^)]*\)', '', normalized)

        normalized = normalized.replace('_', ' ').replace('-', ' ')

        normalized = ' '.join(normalized.split())

        words = normalized.split()
        normalized_words = []
        for word in words:
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
        for artifact_id in built_artifact_ids:
            artifact_type = await self._determine_artifact_type(artifact_id)
            if artifact_type:
                await self.builder.deactivate_provisional(artifact_type, artifact_id)

        await self._notify_user_failed(challenge, final_failure)

    async def _determine_artifact_type(self, artifact_id: str) -> Optional[str]:
        """Determine artifact type by querying each table."""
        from sqlalchemy import select
        from app.models.sql.versioned_models import Skill, Prompt, Agent

        async with self.session_factory() as db:
            result = await db.execute(
                select(Skill).where(Skill.id == artifact_id)
            )
            if result.scalar_one_or_none():
                return "skill"

            result = await db.execute(
                select(Prompt).where(Prompt.id == artifact_id)
            )
            if result.scalar_one_or_none():
                return "prompt"

            result = await db.execute(
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

    async def build_on_demand(
        self,
        capability: str,
        context: dict = None,
    ):
        """
        Build a skill on-the-fly for intra-execution self-healing.

        Lightweight path: directly calls SkillTeamOrchestrator.develop_skill()
        without the full blocked-challenge lifecycle, gap plans, or cycles.
        After successful build, injects the skill into topology.

        Args:
            capability: The capability/tool name to build
            context: Optional context (e.g. arguments the tool was called with)

        Returns:
            SkillBuildResult or None on failure
        """
        from app.models.schemas.skill_build_schemas import SkillBuildResult

        logger.info(f"build_on_demand: building skill for '{capability}'")

        try:
            skill_team = self.builder.get_skill_team()
            result = await skill_team.develop_skill(capability=capability)

            if result.success and result.skill_id:
                if result.integration_plan and result.integration_plan.target_agent_id:
                    inject_ok, inject_msg = await self.injector.inject_with_plan(
                        plan=result.integration_plan,
                        skill_id=result.skill_id,
                        capability=capability,
                    )
                else:
                    inject_ok, inject_msg = await self.injector.inject(
                        artifact_type="skill",
                        artifact_id=result.skill_id,
                    )

                logger.info(
                    f"build_on_demand: skill '{result.skill_name}' built and injected "
                    f"(inject_ok={inject_ok}, msg={inject_msg})"
                )
            else:
                logger.warning(
                    f"build_on_demand: failed for '{capability}': "
                    f"{result.failure_reason}"
                )

            return result

        except Exception as e:
            logger.error(f"build_on_demand failed for '{capability}': {e}", exc_info=True)
            return SkillBuildResult(
                success=False,
                failure_reason=f"On-demand build error: {str(e)}",
            )

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
                challenge = await self.queue.get_next_queued()

                if challenge:
                    if challenge.attempt_number > 1:
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
                    await asyncio.sleep(poll_interval_seconds)

            except Exception as e:
                logger.error(f"Intervention loop error: {e}", exc_info=True)
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
    session_factory=None,
    llm_fn: Optional[Callable[[list[dict], dict], Awaitable[str]]] = None,
    embedding_fn: Optional[Callable[[str], Awaitable[list[float]]]] = None,
    structured_llm_fn: Optional[Callable] = None,
    notify_fn: Optional[Callable[[dict], Awaitable[None]]] = None
) -> InterventionOrchestrator:
    """
    Factory function to create fully-wired InterventionOrchestrator.

    Args:
        session_factory: Session-Factory für DB-Zugriff (default: AsyncSessionLocal)
        llm_fn: Async LLM function
        embedding_fn: Async embedding function
        notify_fn: Async notification function

    Returns:
        Fully configured InterventionOrchestrator
    """
    import os

    from app.core.llm_client import LLMClient
    from app.dependencies.dependencies import AsyncSessionLocal
    from app.orchestration.topology.loader import TopologyLoader
    from app.orchestration.shared_memory.service import SharedMemoryService
    from app.orchestration.shared_memory.qdrant_adapter import SharedMemoryQdrantAdapter
    from app.orchestration.context_manager import ContextBudgetManager
    from app.orchestration.analysis.orchestrator import PreExecutionOrchestrator
    from app.orchestration.agents.developer_team import DeveloperTeamOrchestrator
    from app.orchestration.agents.spawner import AgentSpawnerService
    from app.orchestration.agents.registry import RuntimeAgentRegistry

    if session_factory is None:
        session_factory = AsyncSessionLocal

    llm_client = LLMClient()

    qdrant_adapter = None
    shared_memory = None
    try:
        from qdrant_client import QdrantClient
        qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
        qdrant_client = QdrantClient(url=qdrant_url)
        qdrant_adapter = SharedMemoryQdrantAdapter(qdrant_client)
        await qdrant_adapter.ensure_collections()

        sm_db = session_factory()
        shared_memory = SharedMemoryService(
            db=sm_db,
            qdrant_adapter=qdrant_adapter,
            context_manager=ContextBudgetManager(),
            embedding_fn=embedding_fn
        )
    except Exception as e:
        logger.warning(f"Qdrant nicht erreichbar, SharedMemory deaktiviert: {e}")

    topology_loader = TopologyLoader(session_factory)
    await topology_loader.load()

    registry = RuntimeAgentRegistry(max_concurrent_agents=5)
    spawner = AgentSpawnerService(registry, llm_client)
    developer_team = DeveloperTeamOrchestrator(
        spawner=spawner,
        llm_client=llm_client,
        registry=registry
    )

    pre_execution = PreExecutionOrchestrator(
        topology_loader=topology_loader,
        shared_memory=shared_memory,
        embedding_fn=embedding_fn,
        structured_llm_fn=structured_llm_fn,
    )

    queue_manager = BlockedChallengeQueue(session_factory)
    capability_builder = CapabilityBuilder(developer_team, session_factory)
    injector = CapabilityInjector(topology_loader, session_factory)
    gap_plan_service = GapPlanService(session_factory)

    async def llm_wrapper(messages: list[dict]) -> str:
        if llm_fn:
            return await llm_fn(messages, {})
        return ""

    prompt_improver = AgentPromptImprover(session_factory, llm_fn=llm_wrapper)

    from app.feedback_loop.analysis.failure_analyzer import FailureAnalyzer
    failure_analyzer = FailureAnalyzer(session_factory, llm_client)

    gap_plan_executor = GapPlanExecutor(
        gap_plan_service=gap_plan_service,
        capability_builder=capability_builder,
        prompt_improver=prompt_improver,
        injector=injector,
        session_factory=session_factory,
        failure_analyzer=failure_analyzer,
    )

    return InterventionOrchestrator(
        queue_manager=queue_manager,
        capability_builder=capability_builder,
        injector=injector,
        pre_execution_orchestrator=pre_execution,
        gap_plan_service=gap_plan_service,
        gap_plan_executor=gap_plan_executor,
        session_factory=session_factory,
        notify_fn=notify_fn
    )
