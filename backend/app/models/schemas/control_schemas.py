from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel, Field, ConfigDict


ImprovementStatusType = Literal["pending", "testing", "success", "failed", "rolled_back"]

ArtifactType = Literal["prompt", "agent", "skill"]


class ImprovementAttemptCreate(BaseModel):
    """
    Schema for creating a new improvement attempt.

    Validates all required fields for tracking an improvement attempt.
    The fingerprint identifies the finding for 3-strike rule enforcement.
    """
    finding_fingerprint: str = Field(
        ...,
        min_length=32,
        max_length=64,
        description="Hash of finding for 3-strike tracking (32-64 chars)"
    )
    artifact_type: ArtifactType = Field(
        ...,
        description="Type of artifact being modified: prompt, agent, or skill"
    )
    artifact_id: str = Field(
        ...,
        min_length=36,
        max_length=36,
        description="UUID of the artifact being modified"
    )
    version_before: int = Field(
        ...,
        ge=0,
        description="Version index before change"
    )
    attempt_number: int = Field(
        default=1,
        ge=1,
        le=3,
        description="Which attempt this is (1, 2, or 3)"
    )
    ab_test_id: Optional[str] = Field(
        default=None,
        min_length=36,
        max_length=36,
        description="Reference to A/B test (Phase 4)"
    )


class ImprovementAttemptResponse(BaseModel):
    """
    Schema for improvement attempt API responses.

    Maps directly from database model with from_attributes enabled.
    """
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="UUID primary key")
    finding_fingerprint: str = Field(
        ...,
        description="Hash of finding for 3-strike tracking"
    )
    attempt_number: int = Field(
        ...,
        description="Which attempt this is (1, 2, or 3)"
    )
    artifact_type: str = Field(
        ...,
        description="Type of artifact being modified"
    )
    artifact_id: str = Field(
        ...,
        description="UUID of the artifact being modified"
    )
    version_before: int = Field(
        ...,
        description="Version index before change"
    )
    version_after: Optional[int] = Field(
        None,
        description="Version index after change"
    )
    status: str = Field(
        ...,
        description="Status: pending, testing, success, failed, rolled_back"
    )
    failure_reason: Optional[str] = Field(
        None,
        description="Reason for failure if status is failed"
    )
    ab_test_id: Optional[str] = Field(
        None,
        description="Reference to A/B test"
    )
    created_at: datetime = Field(
        ...,
        description="When the attempt was created"
    )
    completed_at: Optional[datetime] = Field(
        None,
        description="When the attempt completed"
    )


class ImprovementAction(BaseModel):
    """
    Single improvement action approved by Control Agent.

    Represents one improvement to be A/B tested, with artifact target
    and metric weights for composite score calculation.
    """
    finding_index: int = Field(
        ...,
        ge=0,
        description="Index in prioritized findings list"
    )
    artifact_type: ArtifactType = Field(
        ...,
        description="Type of artifact to modify: prompt, agent, or skill"
    )
    artifact_id: str = Field(
        ...,
        min_length=36,
        max_length=36,
        description="UUID of artifact to modify"
    )
    improvement_description: str = Field(
        ...,
        min_length=10,
        description="What change to make"
    )
    metric_weights: dict[str, float] = Field(
        default_factory=lambda: {"quality": 0.5, "latency": 0.3, "error_rate": 0.2},
        description="Weights for composite A/B score (must sum to 1.0)"
    )
    rationale: str = Field(
        ...,
        min_length=10,
        description="Why this improvement was chosen"
    )


class ControlDecision(BaseModel):
    """
    Complete decision output from Control Agent.

    Contains approved improvements (max 3 per batch), deferred findings
    for next cycle, and rejected findings with reasoning.
    """
    approved_improvements: list[ImprovementAction] = Field(
        default_factory=list,
        max_length=3,
        description="Improvements approved for A/B testing (max 3)"
    )
    deferred_findings: list[int] = Field(
        default_factory=list,
        description="Finding indices deferred to next cycle"
    )
    rejected_findings: list[int] = Field(
        default_factory=list,
        description="Finding indices rejected (info-level, 3-strikes, etc.)"
    )
    reasoning: str = Field(
        ...,
        min_length=20,
        description="Explanation of overall decision logic"
    )


class ABTestResult(BaseModel):
    """
    Result from an A/B test (Phase 4 implementation).

    Captures metrics for both variants, statistical significance,
    and effect size for improvement validation.
    """
    test_id: str = Field(
        ...,
        description="UUID of the A/B test"
    )
    variant_a_metrics: dict[str, float] = Field(
        ...,
        description="Baseline metrics {metric_name: value}"
    )
    variant_b_metrics: dict[str, float] = Field(
        ...,
        description="Improvement metrics {metric_name: value}"
    )
    p_value: float = Field(
        ...,
        ge=0,
        le=1,
        description="Statistical p-value"
    )
    effect_size: float = Field(
        ...,
        description="Effect size (Cohen's d or relative %)"
    )
    is_significant: bool = Field(
        ...,
        description="True if p < 0.05 and effect > 10%"
    )
    sample_size_a: int = Field(
        ...,
        ge=0,
        description="Baseline sample count"
    )
    sample_size_b: int = Field(
        ...,
        ge=0,
        description="Improvement sample count"
    )
