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
    QUEUED = "queued"
    BUILDING = "building"
    BUILT = "built"
    INJECTED = "injected"
    RESOLVED = "resolved"
    FAILED = "failed"
    CANCELLED = "cancelled"


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

    challenge_text = Column(Text, nullable=False)

    assessment_result = Column(JSON, nullable=False)
    gaps_snapshot = Column(JSON, nullable=False)

    status = Column(String(20), nullable=False, default="queued")

    attempt_number = Column(Integer, nullable=False, default=1)
    max_attempts = Column(Integer, nullable=False, default=5)

    built_capability_ids = Column(JSON, nullable=False, default=list)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    failure_reasons = Column(JSON, nullable=False, default=list)

    execution_results = Column(JSON, nullable=True)

    build_plan = Column(JSON, nullable=True)
    build_plan_status = Column(String(20), nullable=True, default="pending")


class UserSettings(Base):
    """
    User settings for system behavior.

    Stores preferences like auto_apply for autonomous capability building.
    """
    __tablename__ = "user_settings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), nullable=False, unique=True, index=True)

    auto_apply = Column(Boolean, nullable=False, default=False)
    notify_on_build = Column(Boolean, nullable=False, default=True)
    notify_on_execution = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
