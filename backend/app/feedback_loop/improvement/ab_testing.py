"""
A/B Test Service for lifecycle orchestration of A/B tests.

This service coordinates all A/B testing operations:
- Creating tests (with active test checking)
- Traffic splitting (50/50 random assignment)
- Sample recording with quality scoring and composite metrics
- Test completion with statistical significance testing
- Auto-promotion on success, auto-rollback on failure

Part of the A/B testing infrastructure for validating improvements.
"""
import logging
import random
from dataclasses import dataclass
from typing import Optional

from app.models.schemas.ab_test_schemas import ABTestCreate, ABTestSampleCreate
from app.models.sql.ab_test_models import ABTest, ABTestSample
from app.repositories.ab_test_repository import ABTestRepository
from app.repositories.improvement_repository import ImprovementRepository
from app.feedback_loop.decisions.quality_judge import QualityJudgeService
from app.feedback_loop.improvement.rollback import RollbackService
from app.feedback_loop.analysis.statistical import StatisticalAnalyzer

log = logging.getLogger(__name__)


@dataclass
class ABTestResult:
    """
    Result from A/B test statistical analysis.

    This is the internal result structure returned by compute_result().
    Maps directly from StatisticalAnalyzer.SignificanceResult to database fields.

    Attributes:
        test_id: UUID of the A/B test.
        p_value: Statistical p-value from Welch's t-test.
        effect_size: Cohen's d effect size.
        is_significant: True if BOTH p < 0.05 AND relative improvement > 10%.
        confidence_interval_low: Lower bound of 95% CI for mean difference.
        confidence_interval_high: Upper bound of 95% CI for mean difference.
        baseline_mean: Mean composite score for baseline variant.
        improvement_mean: Mean composite score for improvement variant.
        sample_count_baseline: Number of baseline samples.
        sample_count_improvement: Number of improvement samples.
    """

    test_id: str
    p_value: float
    effect_size: float
    is_significant: bool
    confidence_interval_low: float
    confidence_interval_high: float
    baseline_mean: float
    improvement_mean: float
    sample_count_baseline: int
    sample_count_improvement: int


class ABTestService:
    """
    Orchestrates the complete A/B test lifecycle.

    Handles test creation with active test constraints, 50/50 traffic splitting,
    sample recording with LLM-based quality scoring, and test completion with
    auto-promotion or auto-rollback.

    Dependencies:
    - ABTestRepository: Persistence for tests and samples
    - ImprovementRepository: Status updates for improvement attempts
    - QualityJudgeService: LLM-as-judge quality scoring
    - StatisticalAnalyzer: Significance testing and composite scoring
    - RollbackService: Rollback on failed tests

    Example:
        async with get_session() as session:
            ab_test_repo = ABTestRepository(session)
            improvement_repo = ImprovementRepository(session)
            quality_judge = QualityJudgeService(llm_client)
            stats = StatisticalAnalyzer()
            rollback = RollbackService(version_service, improvement_repo)

            ab_test_service = ABTestService(
                ab_test_repo=ab_test_repo,
                improvement_repo=improvement_repo,
                quality_judge=quality_judge,
                statistical_analyzer=stats,
                rollback_service=rollback,
            )

            # Create test
            test = await ab_test_service.create_test(...)

            # Record samples during execution
            variant = ab_test_service.assign_variant()
            sample = await ab_test_service.record_sample(...)

            # Test auto-completes when minimum samples reached
    """

    def __init__(
        self,
        ab_test_repo: ABTestRepository,
        improvement_repo: ImprovementRepository,
        quality_judge: QualityJudgeService,
        statistical_analyzer: StatisticalAnalyzer,
        rollback_service: RollbackService,
    ):
        """
        Initialize A/B test service with dependencies.

        Args:
            ab_test_repo: Repository for test/sample persistence.
            improvement_repo: Repository for improvement attempt status.
            quality_judge: Service for LLM-based quality scoring.
            statistical_analyzer: Service for significance testing.
            rollback_service: Service for rollback operations.
        """
        self.ab_test_repo = ab_test_repo
        self.improvement_repo = improvement_repo
        self.quality_judge = quality_judge
        self.stats = statistical_analyzer
        self.rollback = rollback_service

    async def create_test(
        self,
        improvement_attempt_id: str,
        artifact_type: str,
        artifact_id: str,
        version_baseline: int,
        version_improvement: int,
        metric_weights: dict[str, float],
    ) -> ABTest:
        """
        Create a new A/B test for an improvement attempt.

        Enforces one-test-per-artifact constraint: if an active test exists,
        queues this improvement for later testing (per CONTEXT.md).

        Args:
            improvement_attempt_id: UUID of the improvement attempt.
            artifact_type: Type of artifact (prompt, agent, skill).
            artifact_id: UUID of the artifact being tested.
            version_baseline: Baseline version index.
            version_improvement: Improvement version index.
            metric_weights: Weights for composite score calculation.

        Returns:
            Created ABTest in "pending" status.

        Raises:
            ValueError: If improvement_attempt_id is invalid.
        """
        log.info(
            f"Creating A/B test for improvement_attempt_id={improvement_attempt_id}, "
            f"artifact={artifact_type}:{artifact_id[:8]}..."
        )

        # Check for active test on this artifact
        active_test = await self.ab_test_repo.get_active_test_for_artifact(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
        )

        if active_test:
            log.info(
                f"Active test id={active_test.id} exists for "
                f"artifact={artifact_type}:{artifact_id[:8]}..., "
                f"queueing improvement_attempt_id={improvement_attempt_id}"
            )
            await self.ab_test_repo.queue_improvement(
                artifact_type=artifact_type,
                artifact_id=artifact_id,
                improvement_attempt_id=improvement_attempt_id,
            )
            # Note: Improvement remains in "pending" status, not "testing"
            # Control Agent can check this and decide to proceed or wait
            raise ValueError(
                f"Active test already running for {artifact_type}:{artifact_id}, "
                f"improvement queued for testing after completion"
            )

        # Create new test
        test_data = ABTestCreate(
            improvement_attempt_id=improvement_attempt_id,
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            version_baseline=version_baseline,
            version_improvement=version_improvement,
            metric_weights=metric_weights,
        )

        test = await self.ab_test_repo.create_test(test_data)

        # Update improvement attempt status to "testing"
        await self.improvement_repo.update_status(
            attempt_id=improvement_attempt_id,
            status="testing",
        )

        log.info(
            f"Created A/B test id={test.id}, "
            f"status=pending, "
            f"improvement_attempt_id={improvement_attempt_id}"
        )

        return test

    def assign_variant(self) -> str:
        """
        Assign variant for an execution (50/50 random split).

        Uses simple random assignment for traffic splitting. Per RESEARCH.md,
        simple random is sufficient for research context.

        Returns:
            "baseline" or "improvement" with equal probability.
        """
        # 50/50 split
        variant = "baseline" if random.random() < 0.5 else "improvement"
        log.debug(f"Assigned variant: {variant}")
        return variant

    async def record_sample(
        self,
        test_id: str,
        execution_id: str,
        variant: str,
        input_content: str,
        output_content: str,
        latency_ms: float,
        is_error: bool,
        latency_baseline: float = 1000.0,
    ) -> ABTestSample:
        """
        Record a sample for an A/B test with quality scoring and composite metric.

        Calls QualityJudgeService to score quality via LLM-as-judge, then computes
        composite score using StatisticalAnalyzer. After recording, checks if test
        has minimum samples and auto-completes if ready.

        Args:
            test_id: UUID of the A/B test.
            execution_id: UUID of the execution being sampled.
            variant: "baseline" or "improvement".
            input_content: User input for quality scoring.
            output_content: Agent output for quality scoring.
            latency_ms: Execution latency in milliseconds.
            is_error: True if execution errored.
            latency_baseline: Baseline latency for normalization (default 1000ms).

        Returns:
            Created ABTestSample with quality and composite scores.
        """
        log.info(
            f"Recording sample for test={test_id[:8]}..., "
            f"variant={variant}, "
            f"execution_id={execution_id[:8]}..."
        )

        # Get test to access metric_weights
        test = await self.ab_test_repo.get_test(test_id)
        if not test:
            log.error(f"A/B test not found: {test_id}")
            raise ValueError(f"A/B test not found: {test_id}")

        # Get quality score via LLM-as-judge
        try:
            quality_result = await self.quality_judge.score_execution(
                input_content=input_content,
                output_content=output_content,
            )
            quality_score = quality_result.score
            log.debug(
                f"Quality score: {quality_score:.3f} - {quality_result.rationale[:50]}..."
            )
        except Exception as e:
            log.warning(
                f"Quality scoring failed for execution_id={execution_id}: {e}, "
                f"using neutral score 0.5"
            )
            quality_score = 0.5

        # Compute composite score
        composite_score = self.stats.compute_composite_score(
            quality=quality_score,
            latency_ms=latency_ms,
            is_error=is_error,
            weights=test.metric_weights,
            latency_baseline=latency_baseline,
        )

        log.debug(
            f"Composite score: {composite_score:.3f} "
            f"(quality={quality_score:.3f}, latency={latency_ms:.1f}ms, error={is_error})"
        )

        # Create sample
        sample_data = ABTestSampleCreate(
            test_id=test_id,
            execution_id=execution_id,
            variant=variant,
            quality_score=quality_score,
            latency_ms=latency_ms,
            is_error=is_error,
            composite_score=composite_score,
        )

        sample = await self.ab_test_repo.add_sample(sample_data)

        log.info(
            f"Recorded sample id={sample.id}, "
            f"composite_score={composite_score:.3f}"
        )

        # Check if test is now complete
        if await self.ab_test_repo.has_minimum_samples(test_id):
            log.info(
                f"Test {test_id[:8]}... has minimum samples, triggering completion"
            )
            await self.compute_and_complete_test(test_id)

        return sample

    async def get_test(self, test_id: str) -> Optional[ABTest]:
        """
        Get an A/B test by ID.

        Args:
            test_id: UUID of the test.

        Returns:
            ABTest or None if not found.
        """
        return await self.ab_test_repo.get_test(test_id)

    async def is_test_complete(self, test_id: str) -> bool:
        """
        Check if a test is complete.

        Args:
            test_id: UUID of the test.

        Returns:
            True if status is "completed" or "cancelled", False otherwise.
        """
        test = await self.ab_test_repo.get_test(test_id)
        if not test:
            return False

        return test.status in ("completed", "cancelled")

    async def cancel_test(self, test_id: str) -> bool:
        """
        Cancel an active test.

        Args:
            test_id: UUID of the test to cancel.

        Returns:
            True if cancelled, False if test not found or already complete.
        """
        log.info(f"Cancelling test {test_id}")

        test = await self.ab_test_repo.get_test(test_id)
        if not test:
            log.warning(f"Test not found: {test_id}")
            return False

        if test.status in ("completed", "cancelled"):
            log.warning(f"Test {test_id} already complete, cannot cancel")
            return False

        await self.ab_test_repo.update_test_status(
            test_id=test_id,
            status="cancelled",
        )

        log.info(f"Cancelled test {test_id}")
        return True

    async def compute_result(self, test_id: str) -> ABTestResult:
        """
        Compute statistical result for an A/B test.

        Retrieves all samples for both variants, extracts composite scores,
        and calls StatisticalAnalyzer to determine if improvement is significant.

        Args:
            test_id: UUID of the A/B test.

        Returns:
            ABTestResult with all statistical metrics and significance determination.

        Raises:
            ValueError: If test not found or insufficient samples.
        """
        log.info(f"Computing result for test {test_id[:8]}...")

        # Get test
        test = await self.ab_test_repo.get_test(test_id)
        if not test:
            log.error(f"A/B test not found: {test_id}")
            raise ValueError(f"A/B test not found: {test_id}")

        # Get all samples for both variants
        baseline_samples = await self.ab_test_repo.get_samples(
            test_id=test_id, variant="baseline"
        )
        improvement_samples = await self.ab_test_repo.get_samples(
            test_id=test_id, variant="improvement"
        )

        if not baseline_samples or not improvement_samples:
            log.error(
                f"Insufficient samples for test {test_id}: "
                f"baseline={len(baseline_samples)}, improvement={len(improvement_samples)}"
            )
            raise ValueError(
                f"Insufficient samples: baseline={len(baseline_samples)}, "
                f"improvement={len(improvement_samples)}"
            )

        # Extract composite scores
        baseline_scores = [s.composite_score for s in baseline_samples]
        improvement_scores = [s.composite_score for s in improvement_samples]

        log.info(
            f"Computing significance with baseline n={len(baseline_scores)}, "
            f"improvement n={len(improvement_scores)}"
        )

        # Call statistical analyzer
        sig_result = self.stats.compute_significance(
            baseline_scores=baseline_scores,
            improvement_scores=improvement_scores,
        )

        # Map SignificanceResult -> ABTestResult
        result = ABTestResult(
            test_id=test_id,
            p_value=sig_result.p_value,
            effect_size=sig_result.effect_size,
            is_significant=sig_result.is_significant,
            confidence_interval_low=sig_result.confidence_interval[0],
            confidence_interval_high=sig_result.confidence_interval[1],
            baseline_mean=sig_result.baseline_mean,
            improvement_mean=sig_result.improvement_mean,
            sample_count_baseline=sig_result.sample_size_baseline,
            sample_count_improvement=sig_result.sample_size_improvement,
        )

        log.info(
            f"Result computed for test {test_id[:8]}...: "
            f"p={result.p_value:.4f}, "
            f"effect={result.effect_size:.2f}, "
            f"is_significant={result.is_significant}"
        )

        return result

    async def compute_and_complete_test(self, test_id: str) -> None:
        """
        Compute test result and complete test with auto-promote or auto-rollback.

        If improvement is significant (p < 0.05 AND relative improvement > 10%):
        - Mark improvement attempt as "success"
        - Auto-promote the improvement

        If improvement is NOT significant:
        - Call RollbackService to revert to baseline
        - Mark improvement attempt as "failed" with reason

        Args:
            test_id: UUID of the A/B test.

        Raises:
            ValueError: If test not found or insufficient samples.
        """
        log.info(f"Completing test {test_id[:8]}...")

        # Get test
        test = await self.ab_test_repo.get_test(test_id)
        if not test:
            log.error(f"A/B test not found: {test_id}")
            raise ValueError(f"A/B test not found: {test_id}")

        # Compute result
        result = await self.compute_result(test_id)

        # Update test status with all statistical fields
        await self.ab_test_repo.update_test_status(
            test_id=test_id,
            status="completed",
            p_value=result.p_value,
            effect_size=result.effect_size,
            is_significant=1 if result.is_significant else 0,
            confidence_interval_low=result.confidence_interval_low,
            confidence_interval_high=result.confidence_interval_high,
            baseline_mean=result.baseline_mean,
            improvement_mean=result.improvement_mean,
        )

        # Handle result: auto-promote or auto-rollback
        if result.is_significant:
            # Auto-promote: mark improvement as success
            log.info(
                f"Test {test_id[:8]}...: Improvement SIGNIFICANT "
                f"(p={result.p_value:.4f}, effect={result.effect_size:.2%}), "
                f"auto-promoting"
            )

            await self.improvement_repo.mark_completed(
                attempt_id=test.improvement_attempt_id,
                success=True,
            )

            log.info(
                f"Auto-promoted improvement_attempt_id={test.improvement_attempt_id}"
            )

        else:
            # Auto-rollback: revert to baseline
            log.info(
                f"Test {test_id[:8]}...: Improvement NOT significant "
                f"(p={result.p_value:.4f}, effect={result.effect_size:.2%}), "
                f"rolling back"
            )

            # Get improvement attempt for rollback
            attempt = await self.improvement_repo.get_by_id(
                test.improvement_attempt_id
            )
            if attempt:
                # Call rollback service
                rollback_success = await self.rollback.rollback_improvement(
                    attempt=attempt,
                    reason=f"A/B test not significant: p={result.p_value:.4f}",
                )

                if rollback_success:
                    log.info(
                        f"Rollback successful for improvement_attempt_id={attempt.id}"
                    )
                else:
                    log.error(
                        f"Rollback failed for improvement_attempt_id={attempt.id}"
                    )

                # Mark improvement as failed
                await self.improvement_repo.mark_completed(
                    attempt_id=attempt.id,
                    success=False,
                    failure_reason=(
                        f"A/B test not significant: p={result.p_value:.4f}, "
                        f"effect={result.effect_size:.2%}"
                    ),
                )
            else:
                log.error(
                    f"Improvement attempt not found: {test.improvement_attempt_id}"
                )

        log.info(f"Test {test_id[:8]}... completed")

        # Update test status to reflect completion timestamp
        await self.ab_test_repo.get_test(test_id)  # Refresh for logging
