"""
Intervention models for blocked challenge queue.

Stores challenges that are blocked due to capability gaps.
Used by InterventionOrchestrator to track retry attempts and capability building.
"""
import uuid
from enum import Enum as PyEnum
from sqlalchemy import Column, String, Text, JSON, Integer, DateTime, Boolean, func
from sqlalchemy.dialects.postgresql import ENUM

from app.models.sql.base import Base


class ChallengeStatus(str, PyEnum):
    """
    Status of blocked challenge in intervention queue.

    Lifecycle: QUEUED -> BUILDING -> BUILT -> INJECTED -> RESOLVED
    Terminal states: RESOLVED, FAILED, CANCELLED
    """
    QUEUED = "queued"              # Waiting for Developer Team
    BUILDING = "building"          # Developer Team actively working
    BUILT = "built"                # Capability built, ready for injection
    INJECTED = "injected"          # Injected into topology, ready for retry
    RESOLVED = "resolved"          # Challenge successfully executed after intervention
    FAILED = "failed"              # Failed after max attempts (5 per CONTEXT)
    CANCELLED = "cancelled"        # User cancelled before resolution


class BlockedChallenge(Base):
    """
    Queue entry for blocked challenges awaiting capability building.

    Per CONTEXT.md: Challenge stored in database queue (survives restarts).
    Tracks retry attempts, built capabilities, and failure reasons.

    Key fields:
    - assessment_result: Full CapabilityAssessment dict from Phase 9
    - gaps_snapshot: List of gap dicts at detection time
    - built_capability_ids: Artifact IDs for rollback if execution fails
    - failure_reasons: List of failure messages per attempt
    """
    __tablename__ = "blocked_challenges"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    execution_id = Column(String(36), nullable=False, index=True)
    project_id = Column(String(36), nullable=False)

    # Challenge content
    challenge_text = Column(Text, nullable=False)

    # Phase 9 assessment context
    assessment_result = Column(JSON, nullable=False)  # Full CapabilityAssessment dict
    gaps_snapshot = Column(JSON, nullable=False)  # List of gap dicts at detection time

    # Queue status (using String instead of Enum to avoid enum sync issues)
    status = Column(String(20), nullable=False, default="queued")

    # Retry tracking
    attempt_number = Column(Integer, nullable=False, default=1)
    max_attempts = Column(Integer, nullable=False, default=5)

    # Built capabilities (for rollback if execution fails)
    built_capability_ids = Column(JSON, nullable=False, default=list)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    # Failure tracking
    failure_reasons = Column(JSON, nullable=False, default=list)

    # Execution results (from orchestrator output)
    execution_results = Column(JSON, nullable=True)

    # Build plan for user approval
    build_plan = Column(JSON, nullable=True)  # BuildPlan dict
    build_plan_status = Column(String(20), nullable=True, default="pending")  # pending, approved, rejected, in_progress, completed, failed


class UserSettings(Base):
    """
    User settings for system behavior.

    Stores preferences like auto_apply for autonomous capability building.
    """
    __tablename__ = "user_settings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), nullable=False, unique=True, index=True)  # For future multi-user support

    # Auto-apply settings
    auto_apply = Column(Boolean, nullable=False, default=False)
    notify_on_build = Column(Boolean, nullable=False, default=True)
    notify_on_execution = Column(Boolean, nullable=False, default=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
