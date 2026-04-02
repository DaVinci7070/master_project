"""
Pydantic schemas for A/B testing operations.

These schemas handle validation for:
- ABTestCreate: Creating new A/B tests
- ABTestSampleCreate: Recording execution samples
- ABTestResponse: API responses with test results
- Variant: Enum for baseline/improvement assignment
"""
from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel, Field, ConfigDict


# Variant types for A/B test assignment
class Variant:
    """Variant assignment for A/B test traffic splitting."""
    BASELINE = "baseline"
    IMPROVEMENT = "improvement"


# Artifact types that can be A/B tested
ArtifactType = Literal["prompt", "agent", "skill"]

# Test status types
TestStatus = Literal["pending", "running", "completed", "cancelled"]


class ABTestCreate(BaseModel):
    """
    Schema for creating a new A/B test.

    Validates all required fields for starting an A/B test.
    Metric weights determine composite score calculation and must sum to ~1.0.
    """
    improvement_attempt_id: str = Field(
        ...,
        min_length=36,
        max_length=36,
        description="UUID of ImprovementAttempt being tested"
    )
    artifact_type: ArtifactType = Field(
        ...,
        description="Type of artifact being tested: prompt, agent, or skill"
    )
    artifact_id: str = Field(
        ...,
        min_length=36,
        max_length=36,
        description="UUID of the artifact being tested"
    )
    version_baseline: int = Field(
        ...,
        ge=0,
        description="Baseline version index"
    )
    version_improvement: int = Field(
        ...,
        ge=0,
        description="Improvement version index"
    )
    metric_weights: dict[str, float] = Field(
        default_factory=lambda: {"quality": 0.5, "latency": 0.3, "error_rate": 0.2},
        description="Weights for composite score calculation (must sum to ~1.0)"
    )


class ABTestSampleCreate(BaseModel):
    """
    Schema for recording an execution sample during A/B test.

    Captures all metrics for one execution: quality (LLM-as-judge),
    latency (milliseconds), error status, and computed composite score.
    """
    test_id: str = Field(
        ...,
        min_length=36,
        max_length=36,
        description="UUID of the A/B test this sample belongs to"
    )
    execution_id: str = Field(
        ...,
        min_length=36,
        max_length=36,
        description="UUID of ExecutionTelemetry for tracing"
    )
    variant: Literal["baseline", "improvement"] = Field(
        ...,
        description="Variant assignment: 'baseline' or 'improvement'"
    )
    quality_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Quality score from LLM-as-judge (0-1, higher is better)"
    )
    latency_ms: float = Field(
        ...,
        ge=0.0,
        description="Execution latency in milliseconds"
    )
    is_error: bool = Field(
        default=False,
        description="True if execution error, False if success"
    )
    composite_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Weighted composite score (0-1, higher is better)"
    )


class ABTestResponse(BaseModel):
    """
    Schema for A/B test API responses.

    Maps directly from ABTest database model with from_attributes enabled.
    Includes all test configuration, status, sample counts, and statistical results.
    """
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="UUID primary key")
    improvement_attempt_id: str = Field(
        ...,
        description="Reference to ImprovementAttempt being tested"
    )
    artifact_type: str = Field(
        ...,
        description="Type of artifact being tested"
    )
    artifact_id: str = Field(
        ...,
        description="UUID of the artifact being tested"
    )
    version_baseline: int = Field(
        ...,
        description="Baseline version index"
    )
    version_improvement: int = Field(
        ...,
        description="Improvement version index"
    )
    metric_weights: dict[str, float] = Field(
        ...,
        description="Weights for composite score calculation"
    )
    status: str = Field(
        ...,
        description="Status: pending, running, completed, cancelled"
    )
    samples_baseline: int = Field(
        ...,
        description="Number of samples collected for baseline variant"
    )
    samples_improvement: int = Field(
        ...,
        description="Number of samples collected for improvement variant"
    )
    p_value: Optional[float] = Field(
        None,
        description="Statistical p-value from Welch's t-test"
    )
    effect_size: Optional[float] = Field(
        None,
        description="Cohen's d effect size"
    )
    is_significant: Optional[int] = Field(
        None,
        description="1 if significant, 0 if not, NULL if incomplete"
    )
    confidence_interval_low: Optional[float] = Field(
        None,
        description="Lower bound of 95% confidence interval for difference"
    )
    confidence_interval_high: Optional[float] = Field(
        None,
        description="Upper bound of 95% confidence interval for difference"
    )
    created_at: datetime = Field(
        ...,
        description="When the test was created"
    )
    completed_at: Optional[datetime] = Field(
        None,
        description="When the test completed"
    )
    queued_ids: list[str] = Field(
        default_factory=list,
        description="List of improvement_attempt_ids waiting to test on this artifact"
    )


class ABTestSampleResponse(BaseModel):
    """
    Schema for A/B test sample API responses.

    Maps directly from ABTestSample database model.
    """
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="UUID primary key")
    test_id: str = Field(
        ...,
        description="Reference to ABTest"
    )
    execution_id: str = Field(
        ...,
        description="Reference to ExecutionTelemetry for tracing"
    )
    variant: str = Field(
        ...,
        description="Variant assignment: 'baseline' or 'improvement'"
    )
    quality_score: float = Field(
        ...,
        description="Quality score from LLM-as-judge (0-1)"
    )
    latency_ms: float = Field(
        ...,
        description="Execution latency in milliseconds"
    )
    is_error: int = Field(
        ...,
        description="1 if execution error, 0 if success"
    )
    composite_score: float = Field(
        ...,
        description="Weighted composite score (0-1)"
    )
    created_at: datetime = Field(
        ...,
        description="When the sample was created"
    )
