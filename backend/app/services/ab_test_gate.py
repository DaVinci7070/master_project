"""
A/B test gate protocol and stub implementation.

This module defines the interface for A/B testing that Phase 4 will implement.
Phase 3 uses StubABTestGate to test control flow without real A/B infrastructure.

Phase 3 vs Phase 4 boundary:
- Phase 3: Control Agent uses ABTestGate protocol, StubABTestGate auto-passes/fails
- Phase 4: Real ABTestGate implementation with statistical significance testing,
           traffic routing, and sample collection

The ABTestGate protocol allows dependency injection:
    gate: ABTestGate = StubABTestGate()  # Phase 3
    gate: ABTestGate = RealABTestGate()  # Phase 4
"""
from typing import Protocol, Optional

from app.models.schemas.control_schemas import ABTestResult
from app.services.ab_test_service import ABTestService


class ABTestGate(Protocol):
    """
    Interface for A/B testing gate that Phase 4 implements.

    The Control Agent uses this interface to start tests and check results.
    Phase 3 uses StubABTestGate for testing the control flow.
    Phase 4 replaces with real implementation.

    Methods:
        start_test: Begin A/B test for an improvement
        get_result: Get test result if complete
        is_complete: Check if test has sufficient data
        cancel_test: Cancel a running test
    """

    async def start_test(
        self,
        improvement_attempt_id: str,
        artifact_type: str,
        artifact_id: str,
        version_baseline: int,
        version_improvement: int,
        metric_weights: dict[str, float],
    ) -> str:
        """
        Start an A/B test for an improvement.

        Args:
            improvement_attempt_id: UUID of the improvement attempt.
            artifact_type: Type of artifact (prompt, agent, skill).
            artifact_id: UUID of the artifact being tested.
            version_baseline: Version index of baseline (control).
            version_improvement: Version index of improvement (treatment).
            metric_weights: Weights for composite score {metric_name: weight}.

        Returns:
            test_id (UUID string) for tracking the test.
        """
        ...

    async def get_result(self, test_id: str) -> Optional[ABTestResult]:
        """
        Get test result if complete.

        Args:
            test_id: UUID of the test to check.

        Returns:
            ABTestResult if test has enough data for significance determination,
            None if test is still running or doesn't exist.
        """
        ...

    async def is_complete(self, test_id: str) -> bool:
        """
        Check if test has sufficient data for significance determination.

        Args:
            test_id: UUID of the test to check.

        Returns:
            True if test has collected enough samples, False otherwise.
        """
        ...

    async def cancel_test(self, test_id: str) -> bool:
        """
        Cancel a running test.

        Call when rolling back an improvement or aborting due to errors.

        Args:
            test_id: UUID of the test to cancel.

        Returns:
            True if test was cancelled, False if test not found.
        """
        ...


class StubABTestGate:
    """
    Stub implementation that auto-approves or rejects improvements.

    Used in Phase 3 to test control flow without real A/B infrastructure.
    Replace with real implementation in Phase 4.

    The auto_pass parameter controls test outcomes:
    - auto_pass=True: All tests pass with significant improvement
    - auto_pass=False: All tests fail with no significant improvement

    This allows testing both paths through the control flow:
        # Test success path
        gate = StubABTestGate(auto_pass=True)

        # Test failure path
        gate = StubABTestGate(auto_pass=False)

    Example:
        gate = StubABTestGate(auto_pass=True)
        test_id = await gate.start_test(
            improvement_attempt_id="uuid",
            artifact_type="prompt",
            artifact_id="prompt-uuid",
            version_baseline=0,
            version_improvement=1,
            metric_weights={"quality": 0.5, "latency": 0.3, "error_rate": 0.2}
        )

        result = await gate.get_result(test_id)
        print(result.is_significant)  # True (since auto_pass=True)
    """

    def __init__(self, auto_pass: bool = True):
        """
        Initialize the stub A/B test gate.

        Args:
            auto_pass: If True, all tests pass with significant improvement.
                       If False, all tests fail with no significant change.
        """
        self.auto_pass = auto_pass
        self._tests: dict[str, dict] = {}

    async def start_test(
        self,
        improvement_attempt_id: str,
        artifact_type: str,
        artifact_id: str,
        version_baseline: int,
        version_improvement: int,
        metric_weights: dict[str, float],
    ) -> str:
        """
        Start a stub A/B test.

        Creates a test ID and stores test metadata. The test immediately
        "completes" since this is a stub.

        Args:
            improvement_attempt_id: UUID of the improvement attempt.
            artifact_type: Type of artifact being tested.
            artifact_id: UUID of the artifact.
            version_baseline: Version index of baseline.
            version_improvement: Version index of improvement.
            metric_weights: Weights for composite score.

        Returns:
            Test ID in format "stub-test-{improvement_id[:8]}".
        """
        test_id = f"stub-test-{improvement_attempt_id[:8]}"
        self._tests[test_id] = {
            "improvement_id": improvement_attempt_id,
            "artifact_type": artifact_type,
            "artifact_id": artifact_id,
            "version_baseline": version_baseline,
            "version_improvement": version_improvement,
            "weights": metric_weights,
        }
        return test_id

    async def get_result(self, test_id: str) -> Optional[ABTestResult]:
        """
        Get stub test result.

        Returns pre-configured pass/fail result based on auto_pass setting.

        Args:
            test_id: UUID of the test.

        Returns:
            ABTestResult with pass/fail metrics, or None if test not found.
        """
        if test_id not in self._tests:
            return None

        if self.auto_pass:
            # Passing result: significant improvement
            return ABTestResult(
                test_id=test_id,
                variant_a_metrics={
                    "quality": 0.80,
                    "latency": 100.0,
                    "error_rate": 0.05,
                },
                variant_b_metrics={
                    "quality": 0.90,
                    "latency": 95.0,
                    "error_rate": 0.03,
                },
                p_value=0.01,
                effect_size=0.125,  # 12.5% improvement
                is_significant=True,
                sample_size_a=100,
                sample_size_b=100,
            )
        else:
            # Failing result: no significant improvement (slight degradation)
            return ABTestResult(
                test_id=test_id,
                variant_a_metrics={
                    "quality": 0.80,
                    "latency": 100.0,
                    "error_rate": 0.05,
                },
                variant_b_metrics={
                    "quality": 0.78,
                    "latency": 105.0,
                    "error_rate": 0.06,
                },
                p_value=0.35,
                effect_size=-0.02,  # 2% degradation
                is_significant=False,
                sample_size_a=100,
                sample_size_b=100,
            )

    async def is_complete(self, test_id: str) -> bool:
        """
        Check if stub test is complete.

        Stub tests are immediately complete once started.

        Args:
            test_id: UUID of the test.

        Returns:
            True if test exists (and is therefore complete), False otherwise.
        """
        return test_id in self._tests

    async def cancel_test(self, test_id: str) -> bool:
        """
        Cancel a stub test.

        Removes the test from tracking.

        Args:
            test_id: UUID of the test to cancel.

        Returns:
            True if test was found and removed, False otherwise.
        """
        if test_id in self._tests:
            del self._tests[test_id]
            return True
        return False

    async def route_execution(self, artifact_type: str, artifact_id: str) -> tuple[Optional[str], Optional[str]]:
        """
        Stub: Always returns (None, None) - no test routing.

        Args:
            artifact_type: Type of artifact (prompt, agent, skill).
            artifact_id: UUID of the artifact.

        Returns:
            (None, None) - stub does not route traffic.
        """
        return None, None

    async def record_execution(
        self,
        test_id: str,
        execution_id: str,
        variant: str,
        input_content: str,
        output_content: str,
        latency_ms: float,
        is_error: bool,
    ) -> None:
        """
        Stub: No-op for sample recording.

        Args:
            test_id: ID of the active test.
            execution_id: ID of this execution.
            variant: Which variant was used ("baseline" or "improvement").
            input_content: User input for quality scoring.
            output_content: Agent output for quality scoring.
            latency_ms: Execution latency in milliseconds.
            is_error: True if execution resulted in error.
        """
        pass

    def get_test_info(self, test_id: str) -> Optional[dict]:
        """
        Get test metadata (stub-specific method for debugging).

        Args:
            test_id: UUID of the test.

        Returns:
            Test metadata dict or None if not found.
        """
        return self._tests.get(test_id)


class RealABTestGate:
    """
    Real implementation of ABTestGate with statistical A/B testing.

    Replaces StubABTestGate for production use. Delegates all operations
    to ABTestService which handles:
    - Test creation and lifecycle
    - Quality scoring via LLM-as-judge
    - Statistical significance testing
    - Auto-promote/rollback

    Usage:
        # Production
        gate = RealABTestGate(ab_test_service=ab_service)

        # Testing (use stub)
        gate = StubABTestGate(auto_pass=True)
    """

    def __init__(self, ab_test_service: ABTestService):
        """
        Initialize with ABTestService dependency.

        Args:
            ab_test_service: Service that handles all A/B test operations.
        """
        self.ab_service = ab_test_service

    async def start_test(
        self,
        improvement_attempt_id: str,
        artifact_type: str,
        artifact_id: str,
        version_baseline: int,
        version_improvement: int,
        metric_weights: dict[str, float],
    ) -> str:
        """Start A/B test, returns test_id."""
        test = await self.ab_service.create_test(
            improvement_attempt_id=improvement_attempt_id,
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            version_baseline=version_baseline,
            version_improvement=version_improvement,
            metric_weights=metric_weights,
        )
        return test.id

    async def get_result(self, test_id: str) -> Optional[ABTestResult]:
        """Get result if complete, None if still running."""
        if not await self.is_complete(test_id):
            return None

        # Get internal result from ABTestService
        internal_result = await self.ab_service.compute_result(test_id)

        # Map internal ABTestResult to control_schemas.ABTestResult
        from app.models.schemas.control_schemas import ABTestResult as ControlABTestResult

        return ControlABTestResult(
            test_id=internal_result.test_id,
            variant_a_metrics={
                "quality": internal_result.baseline_mean,
                "latency": 0.0,  # Not tracked separately in composite
                "error_rate": 0.0,  # Not tracked separately in composite
            },
            variant_b_metrics={
                "quality": internal_result.improvement_mean,
                "latency": 0.0,  # Not tracked separately in composite
                "error_rate": 0.0,  # Not tracked separately in composite
            },
            p_value=internal_result.p_value,
            effect_size=internal_result.effect_size,
            is_significant=internal_result.is_significant,
            sample_size_a=internal_result.sample_count_baseline,
            sample_size_b=internal_result.sample_count_improvement,
        )

    async def is_complete(self, test_id: str) -> bool:
        """Check if minimum samples reached."""
        return await self.ab_service.is_test_complete(test_id)

    async def cancel_test(self, test_id: str) -> bool:
        """Cancel a running test."""
        return await self.ab_service.cancel_test(test_id)

    async def route_execution(
        self,
        artifact_type: str,
        artifact_id: str,
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Route an execution to a variant if test is active.

        Call this before executing with an artifact to determine
        if the execution should use baseline or improvement variant.

        Args:
            artifact_type: Type of artifact (prompt, agent, skill).
            artifact_id: UUID of the artifact.

        Returns:
            Tuple of (test_id, variant) if active test exists.
            Returns (None, None) if no active test for artifact.
        """
        # Get active test for this artifact
        test = await self.ab_service.ab_test_repo.get_active_test_for_artifact(
            artifact_type, artifact_id
        )

        if not test:
            return None, None

        # Assign variant using traffic splitter
        variant = self.ab_service.assign_variant()

        return test.id, variant

    async def record_execution(
        self,
        test_id: str,
        execution_id: str,
        variant: str,
        input_content: str,
        output_content: str,
        latency_ms: float,
        is_error: bool,
    ) -> None:
        """
        Record execution result as A/B test sample.

        Call this after execution completes to record metrics.
        The sample is automatically scored for quality via LLM.

        If this sample reaches minimum threshold, test automatically
        completes with auto-promote or auto-rollback.

        Args:
            test_id: ID of the active test.
            execution_id: ID of this execution.
            variant: Which variant was used ("baseline" or "improvement").
            input_content: User input for quality scoring.
            output_content: Agent output for quality scoring.
            latency_ms: Execution latency in milliseconds.
            is_error: True if execution resulted in error.
        """
        await self.ab_service.record_sample(
            test_id=test_id,
            execution_id=execution_id,
            variant=variant,
            input_content=input_content,
            output_content=output_content,
            latency_ms=latency_ms,
            is_error=is_error,
        )
