"""
Gap Plan Executor for deterministic gap resolution.

Key difference from old approach:
- Works through FIXED gap list (no re-analysis during build)
- Updates gap status as it goes
- Only re-assesses at END of cycle
"""
import logging
from typing import Optional


from app.models.schemas.intervention_schemas import BuildResult
from app.models.sql.gap_plan_models import GapStatus
from app.services.gap_plan_service import GapPlanService
from app.services.failure_analyzer import FailureAnalyzer
from app.orchestration.intervention.capability_builder import CapabilityBuilder
from app.orchestration.intervention.injector import CapabilityInjector
from app.services.agent_prompt_improver import AgentPromptImprover

logger = logging.getLogger(__name__)


class GapPlanExecutor:
    """
    Executes a capability gap plan deterministically.

    Key behaviors:
    1. Works through fixed gap list (no re-analysis during build)
    2. Updates gap status as each gap is processed
    3. Routes to appropriate builder based on gap_type
    4. Tracks all built artifacts for final injection
    """

    def __init__(
        self,
        gap_plan_service: GapPlanService,
        capability_builder: CapabilityBuilder,
        prompt_improver: AgentPromptImprover,
        injector: CapabilityInjector,
        session_factory,
        failure_analyzer: Optional[FailureAnalyzer] = None,
    ):
        """
        Initialize gap plan executor.

        Args:
            gap_plan_service: Service for gap plan CRUD
            capability_builder: Builder for skills and agents
            prompt_improver: Improver for weak_prompt gaps
            injector: Injector for topology updates
            db: Database session
            failure_analyzer: Analyzer for recording and learning from build attempts
        """
        self.plan_service = gap_plan_service
        self.builder = capability_builder
        self.prompt_improver = prompt_improver
        self.injector = injector
        self.session_factory = session_factory
        self.failure_analyzer = failure_analyzer

    async def execute_plan(
        self,
        plan_id: str,
        challenge_text: str,
        attempt_number: int = 1,
        previous_failures: Optional[list[str]] = None
    ) -> tuple[list[BuildResult], list[str]]:
        """
        Execute a gap plan by working through all gaps sequentially.

        Args:
            plan_id: ID of the gap plan to execute
            challenge_text: Original challenge text for context
            attempt_number: Current attempt number
            previous_failures: List of previous failure reasons

        Returns:
            Tuple of (all_build_results, successful_artifact_ids)
        """
        all_results: list[BuildResult] = []
        successful_artifacts: list[str] = []

        # Start the plan
        plan = await self.plan_service.start_plan(plan_id)
        logger.info(
            f"Executing gap plan: {plan_id[:8]}..., "
            f"total_gaps={plan.total_gaps}, cycle={plan.cycle_number}"
        )

        # Process gaps sequentially
        while True:
            gap_dict = await self.plan_service.get_next_pending_gap(plan_id)

            if not gap_dict:
                # No more pending gaps
                logger.info(f"All gaps processed for plan {plan_id[:8]}...")
                break

            gap_id = gap_dict["id"]
            gap_type = gap_dict["gap_type"]
            affected_capability = gap_dict["affected_capability"]
            severity = gap_dict["severity"]
            description = gap_dict.get("description", "")

            logger.info(
                f"Processing gap: {gap_id[:8]}... "
                f"type={gap_type}, capability={affected_capability}, severity={severity}"
            )

            # Mark as building
            await self.plan_service.update_gap_status(
                plan_id=plan_id,
                gap_id=gap_id,
                status=GapStatus.BUILDING.value
            )

            # Build based on gap type
            result = await self._build_for_gap(
                gap_dict=gap_dict,
                challenge_text=challenge_text,
                attempt_number=attempt_number,
                previous_failures=previous_failures or []
            )

            all_results.append(result)

            if result.success and result.artifact_id:
                # Inject capability — use plan-based injection if available
                if result.integration_plan and result.integration_plan.target_agent_id:
                    inject_success, inject_msg = await self.injector.inject_with_plan(
                        plan=result.integration_plan,
                        skill_id=result.artifact_id,
                        capability=gap_dict["affected_capability"],
                    )
                else:
                    inject_success, inject_msg = await self.injector.inject(
                        artifact_type=result.artifact_type,
                        artifact_id=result.artifact_id
                    )

                if inject_success:
                    successful_artifacts.append(result.artifact_id)

                    # Mark gap as completed
                    await self.plan_service.update_gap_status(
                        plan_id=plan_id,
                        gap_id=gap_id,
                        status=GapStatus.COMPLETED.value,
                        artifact_id=result.artifact_id,
                        artifact_type=result.artifact_type
                    )

                    # Feed success back to FailureAnalyzer
                    if self.failure_analyzer:
                        try:
                            await self.failure_analyzer.record_attempt(
                                capability=affected_capability,
                                code="",
                                success=True,
                                skill_id=result.artifact_id,
                                strategy_id=getattr(result, '_strategy_id', None),
                            )
                            if result.artifact_type == "skill":
                                await self.failure_analyzer.learn_from_success(
                                    capability=affected_capability,
                                    pip_requirements=[],
                                    code="",
                                )
                        except Exception as fa_err:
                            # Session may be stale after topology reload in injector;
                            # rollback so subsequent DB operations still work.
                            async with self.session_factory() as db:
                                await db.rollback()
                            logger.warning(
                                f"FailureAnalyzer record_attempt failed (non-fatal): {fa_err}"
                            )

                    logger.info(
                        f"Gap completed: {gap_id[:8]}... -> "
                        f"{result.artifact_type}/{result.artifact_id[:8]}..."
                    )
                else:
                    # Injection failed
                    await self.plan_service.update_gap_status(
                        plan_id=plan_id,
                        gap_id=gap_id,
                        status=GapStatus.FAILED.value,
                        error_message=f"Injection failed: {inject_msg}"
                    )
                    logger.warning(f"Gap injection failed: {gap_id[:8]}... - {inject_msg}")
            else:
                # Build failed — feed back to FailureAnalyzer
                failure_reason = result.failure_reason or "Unknown build failure"

                if self.failure_analyzer:
                    try:
                        analysis = await self.failure_analyzer.analyze_failure(
                            capability=affected_capability,
                            code="",
                            error_message=failure_reason,
                        )
                        await self.failure_analyzer.record_attempt(
                            capability=affected_capability,
                            code="",
                            success=False,
                            error_type=analysis.error_type,
                            error_message=failure_reason,
                            attempt_number=attempt_number,
                            strategy_id=getattr(result, '_strategy_id', None),
                            error_type_classified=analysis.error_type_classified,
                            lesson_learned=analysis.lesson_learned,
                        )
                    except Exception as fa_err:
                        async with self.session_factory() as db:
                            await db.rollback()
                        logger.warning(
                            f"FailureAnalyzer record_attempt failed (non-fatal): {fa_err}"
                        )

                await self.plan_service.update_gap_status(
                    plan_id=plan_id,
                    gap_id=gap_id,
                    status=GapStatus.FAILED.value,
                    error_message=failure_reason
                )
                logger.warning(
                    f"Gap build failed: {gap_id[:8]}... - {failure_reason}"
                )

        # Complete the plan
        plan = await self.plan_service.get_plan(plan_id)
        final_status = "completed" if plan.failed_gaps == 0 else "partial"
        await self.plan_service.complete_plan(plan_id, final_status)

        logger.info(
            f"Gap plan execution finished: {plan_id[:8]}..., "
            f"completed={plan.completed_gaps}, failed={plan.failed_gaps}, "
            f"artifacts={len(successful_artifacts)}"
        )

        return all_results, successful_artifacts

    async def _build_for_gap(
        self,
        gap_dict: dict,
        challenge_text: str,
        attempt_number: int,
        previous_failures: list[str]
    ) -> BuildResult:
        """
        Build capability for a single gap, routing to appropriate builder.

        Gap types and their handlers:
        - weak_prompt: AgentPromptImprover (improves existing agent prompt)
        - missing_skill: CapabilityBuilder (creates new skill)
        - missing_agent: CapabilityBuilder (creates new agent)
        - configuration_needed: CapabilityBuilder (handled as skill)
        """
        gap_type = gap_dict["gap_type"]
        affected_capability = gap_dict["affected_capability"]
        description = gap_dict.get("description", "")
        severity = gap_dict.get("severity", "important")

        # Ask FailureAnalyzer for strategy if available
        strategy_id = None
        if self.failure_analyzer and gap_type in ("missing_skill", "configuration_needed"):
            proposal = await self.failure_analyzer.propose_strategy(
                capability=affected_capability,
                current_attempt_number=attempt_number,
            )
            strategy_id = proposal.strategy_id
            # Add lessons as hints to previous failures
            if proposal.hints:
                previous_failures = list(previous_failures) + [
                    f"[Lesson] {h}" for h in proposal.hints
                ]
            logger.info(
                f"Strategy proposed for {affected_capability}: {strategy_id} "
                f"(confidence={proposal.confidence:.1f})"
            )

        # Route based on gap type
        if gap_type == "weak_prompt":
            # Use prompt improver for weak_prompt gaps
            return await self.prompt_improver.improve(
                affected_capability=affected_capability,
                gap_description=description,
                challenge_context=challenge_text
            )

        elif gap_type in ("missing_skill", "configuration_needed"):
            # Use capability builder for skill gaps
            from app.models.schemas.analysis_schemas import CapabilityGap, GapType, GapSeverity

            gap = CapabilityGap(
                gap_type=GapType(gap_type),
                affected_capability=affected_capability,
                severity=GapSeverity(severity),
                description=description
            )

            return await self.builder.build_for_gap(
                gap=gap,
                challenge_text=challenge_text,
                attempt_number=attempt_number,
                previous_failures=previous_failures
            )

        elif gap_type == "missing_agent":
            # Use capability builder for agent gaps
            from app.models.schemas.analysis_schemas import CapabilityGap, GapType, GapSeverity

            gap = CapabilityGap(
                gap_type=GapType(gap_type),
                affected_capability=affected_capability,
                severity=GapSeverity(severity),
                description=description
            )

            return await self.builder.build_for_gap(
                gap=gap,
                challenge_text=challenge_text,
                attempt_number=attempt_number,
                previous_failures=previous_failures
            )

        else:
            # Unknown gap type - try generic builder
            logger.warning(f"Unknown gap type '{gap_type}', using generic builder")
            from app.models.schemas.analysis_schemas import CapabilityGap, GapType, GapSeverity

            # Default to missing_skill if unknown
            try:
                gap_type_enum = GapType(gap_type)
            except ValueError:
                gap_type_enum = GapType.MISSING_SKILL

            gap = CapabilityGap(
                gap_type=gap_type_enum,
                affected_capability=affected_capability,
                severity=GapSeverity(severity) if severity in ("critical", "important", "minor") else GapSeverity.IMPORTANT,
                description=description
            )

            return await self.builder.build_for_gap(
                gap=gap,
                challenge_text=challenge_text,
                attempt_number=attempt_number,
                previous_failures=previous_failures
            )

    async def get_plan_progress(self, plan_id: str) -> dict:
        """Get current progress of a gap plan."""
        plan = await self.plan_service.get_plan(plan_id)
        if not plan:
            return {"error": "Plan not found"}

        return {
            "plan_id": plan_id,
            "status": plan.status,
            "cycle_number": plan.cycle_number,
            "total_gaps": plan.total_gaps,
            "completed_gaps": plan.completed_gaps,
            "failed_gaps": plan.failed_gaps,
            "pending_gaps": plan.total_gaps - plan.completed_gaps - plan.failed_gaps,
            "progress_percent": (
                (plan.completed_gaps / plan.total_gaps * 100)
                if plan.total_gaps > 0 else 0
            ),
            "artifacts": await self.plan_service.get_all_built_artifacts(plan_id)
        }
