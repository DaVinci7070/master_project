import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Float, DateTime, JSON, Index

from app.models.sql.base import Base


class ABTest(Base):
    """
    A/B test record for tracking test state and results.

    Tracks test lifecycle from creation through completion, storing:
    - Test configuration (artifact, versions, metric weights)
    - Sample counts for each variant (baseline vs improvement)
    - Statistical results (p-value, effect size, significance)
    - Queue of pending improvements for same artifact

    One test per artifact at a time - new improvements are queued if test running.
    """
    __tablename__ = "ab_test"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="UUID primary key"
    )

    improvement_attempt_id = Column(
        String(36),
        nullable=False,
        index=True,
        doc="Reference to ImprovementAttempt being tested"
    )
    artifact_type = Column(
        String(32),
        nullable=False,
        doc="Type of artifact: prompt, agent, or skill"
    )
    artifact_id = Column(
        String(36),
        nullable=False,
        doc="UUID of the artifact being tested"
    )
    version_baseline = Column(
        Integer,
        nullable=False,
        doc="Baseline version index"
    )
    version_improvement = Column(
        Integer,
        nullable=False,
        doc="Improvement version index"
    )
    metric_weights = Column(
        JSON,
        nullable=False,
        doc="Weights for composite score: {quality, latency, error_rate}"
    )

    status = Column(
        String(32),
        nullable=False,
        default="pending",
        doc="Status: pending, running, completed, cancelled"
    )

    samples_baseline = Column(
        Integer,
        nullable=False,
        default=0,
        doc="Number of samples collected for baseline variant"
    )
    samples_improvement = Column(
        Integer,
        nullable=False,
        default=0,
        doc="Number of samples collected for improvement variant"
    )

    p_value = Column(
        Float,
        nullable=True,
        doc="Statistical p-value from Welch's t-test"
    )
    effect_size = Column(
        Float,
        nullable=True,
        doc="Cohen's d effect size"
    )
    is_significant = Column(
        Integer,
        nullable=True,
        doc="1 if significant (p < 0.05 AND effect > 10%), 0 if not, NULL if incomplete"
    )
    confidence_interval_low = Column(
        Float,
        nullable=True,
        doc="Lower bound of 95% confidence interval for difference"
    )
    confidence_interval_high = Column(
        Float,
        nullable=True,
        doc="Upper bound of 95% confidence interval for difference"
    )

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="When the test was created"
    )
    completed_at = Column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the test completed"
    )

    queued_ids = Column(
        JSON,
        nullable=False,
        default=list,
        doc="List of improvement_attempt_ids waiting to test on this artifact"
    )

    __table_args__ = (
        Index('ix_ab_test_artifact', 'artifact_type', 'artifact_id'),
        Index('ix_ab_test_status', 'status'),
    )

    def __repr__(self) -> str:
        return (
            f"<ABTest("
            f"id={self.id!r}, "
            f"artifact={self.artifact_type}:{self.artifact_id[:8]}..., "
            f"status={self.status!r}, "
            f"samples={self.samples_baseline}/{self.samples_improvement}"
            f")>"
        )


class ABTestSample(Base):
    """
    Individual sample collected during A/B test.

    Each execution during a test creates one sample with metrics:
    - quality_score: 0-1 from LLM-as-judge
    - latency_ms: Raw latency in milliseconds
    - is_error: 0 or 1 indicating success/failure
    - composite_score: Weighted combination of all metrics

    Variant indicates baseline or improvement assignment.
    """
    __tablename__ = "ab_test_sample"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="UUID primary key"
    )

    test_id = Column(
        String(36),
        nullable=False,
        doc="Reference to ABTest (conceptual FK)"
    )
    execution_id = Column(
        String(36),
        nullable=False,
        doc="Reference to ExecutionTelemetry for tracing"
    )

    variant = Column(
        String(16),
        nullable=False,
        doc="Variant assignment: 'baseline' or 'improvement'"
    )

    quality_score = Column(
        Float,
        nullable=False,
        doc="Quality score 0-1 from LLM-as-judge"
    )
    latency_ms = Column(
        Float,
        nullable=False,
        doc="Execution latency in milliseconds"
    )
    is_error = Column(
        Integer,
        nullable=False,
        default=0,
        doc="1 if execution error, 0 if success"
    )

    composite_score = Column(
        Float,
        nullable=False,
        doc="Weighted composite score (higher is better)"
    )

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="When the sample was created"
    )

    __table_args__ = (
        Index('ix_ab_test_sample_test_id', 'test_id'),
        Index('ix_ab_test_sample_variant', 'variant'),
    )

    def __repr__(self) -> str:
        return (
            f"<ABTestSample("
            f"id={self.id!r}, "
            f"test_id={self.test_id[:8]}..., "
            f"variant={self.variant!r}, "
            f"composite_score={self.composite_score:.3f}"
            f")>"
        )
