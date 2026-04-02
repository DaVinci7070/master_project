"""
Capability Gap Plan models for deterministic gap resolution.

Stores the gap plan created during initial analysis, preventing
the endless re-analysis loop by fixing the gap list upfront.

Gap Plan Lifecycle:
1. PENDING - Plan created, gaps identified
2. IN_PROGRESS - Gaps being built
3. COMPLETED - All gaps processed
4. FAILED - Critical failure during execution
"""
import uuid
from enum import Enum as PyEnum
from sqlalchemy import Column, String, Text, JSON, Integer, DateTime, func, Index

from app.models.sql.base import Base


class GapPlanStatus(str, PyEnum):
    """Status of a capability gap plan."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class GapStatus(str, PyEnum):
    """Status of individual gap within a plan."""
    PENDING = "pending"
    BUILDING = "building"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class CapabilityGapPlan(Base):
    """
    Persistent gap plan for deterministic capability building.

    Key design decisions:
    - Gaps are stored as JSON array (not separate table) for simplicity
    - cycle_number tracks retry cycles (max 3)
    - Progress is tracked via completed_gaps/total_gaps

    Gap object schema:
    {
        "id": "uuid",
        "gap_type": "missing_skill|weak_prompt|missing_agent|topology_issue|schema_mismatch",
        "affected_capability": "string",
        "severity": "critical|important|minor",
        "description": "string",
        "status": "pending|building|completed|failed|skipped",
        "artifact_id": "uuid|null",
        "artifact_type": "skill|prompt|agent|null",
        "error_message": "string|null",
        "started_at": "ISO timestamp|null",
        "completed_at": "ISO timestamp|null"
    }
    """
    __tablename__ = "capability_gap_plans"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Foreign keys
    challenge_id = Column(String(36), nullable=False, index=True)
    execution_id = Column(String(36), nullable=True, index=True)

    # Cycle tracking (for multi-cycle resolution)
    cycle_number = Column(Integer, nullable=False, default=1)

    # Plan status
    status = Column(String(20), nullable=False, default="pending")

    # Gaps array (JSONB for PostgreSQL)
    gaps = Column(JSON, nullable=False, default=list)

    # Progress tracking
    total_gaps = Column(Integer, nullable=False, default=0)
    completed_gaps = Column(Integer, nullable=False, default=0)
    failed_gaps = Column(Integer, nullable=False, default=0)

    # Initial assessment context (for reference)
    initial_confidence = Column(String(20), nullable=True)  # MAYBE, CANNOT_DO
    initial_assessment = Column(JSON, nullable=True)  # Full assessment snapshot

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Indexes
    __table_args__ = (
        Index('ix_gap_plan_challenge_cycle', 'challenge_id', 'cycle_number'),
        Index('ix_gap_plan_status', 'status'),
    )

    def get_progress_percentage(self) -> float:
        """Calculate completion percentage."""
        if self.total_gaps == 0:
            return 100.0
        return round((self.completed_gaps / self.total_gaps) * 100, 1)

    def get_next_pending_gap(self) -> dict | None:
        """
        Get next pending gap, sorted by severity.

        Priority: critical > important > minor
        """
        severity_order = {"critical": 0, "important": 1, "minor": 2}

        pending_gaps = [
            g for g in (self.gaps or [])
            if g.get("status") == "pending"
        ]

        if not pending_gaps:
            return None

        # Sort by severity
        pending_gaps.sort(key=lambda g: severity_order.get(g.get("severity", "minor"), 2))

        return pending_gaps[0]

    def update_gap_status(
        self,
        gap_id: str,
        status: str,
        artifact_id: str | None = None,
        artifact_type: str | None = None,
        error_message: str | None = None
    ) -> bool:
        """
        Update status of a specific gap.

        Returns True if gap was found and updated.
        """
        from datetime import datetime, timezone

        for gap in (self.gaps or []):
            if gap.get("id") == gap_id:
                gap["status"] = status
                gap["updated_at"] = datetime.now(timezone.utc).isoformat()

                if status == "building":
                    gap["started_at"] = datetime.now(timezone.utc).isoformat()
                elif status in ("completed", "failed", "skipped"):
                    gap["completed_at"] = datetime.now(timezone.utc).isoformat()

                if artifact_id:
                    gap["artifact_id"] = artifact_id
                if artifact_type:
                    gap["artifact_type"] = artifact_type
                if error_message:
                    gap["error_message"] = error_message

                # Update counters
                self._recalculate_counters()
                return True

        return False

    def _recalculate_counters(self) -> None:
        """Recalculate completed_gaps and failed_gaps from gaps array."""
        completed = 0
        failed = 0

        for gap in (self.gaps or []):
            status = gap.get("status", "pending")
            if status == "completed":
                completed += 1
            elif status == "failed":
                failed += 1

        self.completed_gaps = completed
        self.failed_gaps = failed

    def is_complete(self) -> bool:
        """Check if all gaps have been processed."""
        return self.completed_gaps + self.failed_gaps >= self.total_gaps

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        return {
            "id": self.id,
            "challenge_id": self.challenge_id,
            "execution_id": self.execution_id,
            "cycle_number": self.cycle_number,
            "status": self.status,
            "progress": {
                "total": self.total_gaps,
                "completed": self.completed_gaps,
                "failed": self.failed_gaps,
                "pending": self.total_gaps - self.completed_gaps - self.failed_gaps,
                "percentage": self.get_progress_percentage()
            },
            "gaps": self.gaps,
            "initial_confidence": self.initial_confidence,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
