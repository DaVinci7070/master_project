"""
Improvement models for tracking improvement attempts.

This module implements ImprovementAttempt model for tracking each time
the system attempts to fix a finding. The 3-strike rule uses this model
to prevent infinite improvement loops on the same finding.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Text, DateTime, Index

from app.models.sql.base import Base


class ImprovementAttempt(Base):
    """
    Improvement attempt record for tracking fix attempts per finding.

    Tracks each improvement attempt by finding fingerprint:
    - finding_fingerprint: Hash identifying the finding for 3-strike rule
    - attempt_number: Which attempt this is (1, 2, or 3)
    - artifact_type: What is being modified (prompt, agent, skill)
    - version_before/after: Track version changes for rollback
    - status: Current state of the improvement attempt

    The 3-strike rule: After 3 failed attempts on the same finding
    fingerprint, the system stops trying to fix it automatically.
    """
    __tablename__ = "improvement_attempt"

    # Primary key
    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="UUID primary key"
    )

    # Finding identification for 3-strike rule
    finding_fingerprint = Column(
        String(64),
        nullable=False,
        index=True,
        doc="Hash of finding for 3-strike tracking"
    )

    # Attempt tracking
    attempt_number = Column(
        Integer,
        nullable=False,
        default=1,
        doc="Which attempt this is (1, 2, or 3)"
    )

    # Artifact being modified
    artifact_type = Column(
        String(32),
        nullable=False,
        doc="Type of artifact: prompt, agent, or skill"
    )
    artifact_id = Column(
        String(36),
        nullable=False,
        doc="UUID of the artifact being modified"
    )

    # Version tracking for rollback
    version_before = Column(
        Integer,
        nullable=False,
        doc="Version index before change"
    )
    version_after = Column(
        Integer,
        nullable=True,
        doc="Version index after change (set after improvement applied)"
    )

    # Status tracking
    status = Column(
        String(32),
        nullable=False,
        default="pending",
        doc="Status: pending, testing, success, failed, rolled_back"
    )
    failure_reason = Column(
        Text,
        nullable=True,
        doc="Reason for failure if status is failed"
    )

    # A/B testing reference (Phase 4)
    ab_test_id = Column(
        String(36),
        nullable=True,
        doc="Reference to A/B test (Phase 4)"
    )

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="When the attempt was created"
    )
    completed_at = Column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the attempt completed (success or failure)"
    )

    # Indexes for common query patterns
    __table_args__ = (
        # Filter by fingerprint for 3-strike rule
        Index('ix_improvement_fingerprint', 'finding_fingerprint'),
        # Filter by status for active attempts
        Index('ix_improvement_status', 'status'),
    )

    def __repr__(self) -> str:
        return (
            f"<ImprovementAttempt("
            f"id={self.id!r}, "
            f"fingerprint={self.finding_fingerprint[:8]}..., "
            f"attempt={self.attempt_number}, "
            f"status={self.status!r}"
            f")>"
        )
