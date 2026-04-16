"""
Pydantic schemas for intervention operations.

Handles validation for:
- Intervention requests from Phase 9 routing
- Build results from Developer Team
- Intervention responses to API consumers
- Database operations for blocked challenges
- Build Plans for user approval
"""
from datetime import datetime
from typing import Optional, Literal
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict

from app.models.schemas.skill_build_schemas import SkillIntegrationPlan

from app.models.sql.intervention_models import ChallengeStatus
from app.models.schemas.analysis_schemas import CapabilityAssessment, CapabilityGap


class BuildActionType(str, Enum):
    """Types of build actions the system can take."""
    CREATE_SKILL = "create_skill"
    IMPROVE_PROMPT = "improve_prompt"
    CREATE_AGENT = "create_agent"
    UPDATE_TOPOLOGY = "update_topology"


class BuildPlanItem(BaseModel):
    """
    Single item in a build plan.

    Represents one capability that needs to be built or improved.
    """
    action_type: BuildActionType = Field(
        ...,
        description="Type of build action"
    )
    target_capability: str = Field(
        ...,
        description="Capability being addressed"
    )
    description: str = Field(
        ...,
        description="Human-readable description of what will be built"
    )
    estimated_complexity: Literal["low", "medium", "high"] = Field(
        default="medium",
        description="Estimated complexity of the build"
    )
    affected_agents: list[str] = Field(
        default_factory=list,
        description="Agents that will be affected by this change"
    )
    gap_severity: str = Field(
        default="important",
        description="Severity of the gap being addressed"
    )


class BuildPlan(BaseModel):
    """
    Complete build plan for capability gaps.

    Generated when MAYBE/CANNOT_DO assessment, presented to user for approval.
    """
    challenge_id: str = Field(
        ...,
        description="ID of the challenge this plan is for"
    )
    items: list[BuildPlanItem] = Field(
        ...,
        description="List of build actions to take"
    )
    total_gaps: int = Field(
        ...,
        description="Total number of gaps identified"
    )
    critical_gaps: int = Field(
        default=0,
        description="Number of critical gaps"
    )
    confidence_after_build: str = Field(
        default="CAN_DO (expected)",
        description="Expected confidence level after build"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(),
        description="When plan was created"
    )


class BuildPlanStatus(str, Enum):
    """Status of a build plan."""
    PENDING = "pending"           # Waiting for user approval
    APPROVED = "approved"         # User approved, ready to execute
    REJECTED = "rejected"         # User rejected
    IN_PROGRESS = "in_progress"   # Currently building
    COMPLETED = "completed"       # Build finished successfully
    FAILED = "failed"             # Build failed


class BuildPlanApprovalRequest(BaseModel):
    """Request to approve or reject a build plan."""
    approved: bool = Field(
        ...,
        description="Whether to approve the plan"
    )
    feedback: Optional[str] = Field(
        default=None,
        description="Optional feedback from user"
    )


class BuildPlanResponse(BaseModel):
    """Response containing build plan for user review."""
    plan: BuildPlan = Field(
        ...,
        description="The build plan"
    )
    status: BuildPlanStatus = Field(
        default=BuildPlanStatus.PENDING,
        description="Current status of the plan"
    )
    auto_apply_enabled: bool = Field(
        default=False,
        description="Whether auto-apply is enabled"
    )
    message: str = Field(
        default="",
        description="Status message"
    )


class UserSettings(BaseModel):
    """User settings for the system."""
    auto_apply: bool = Field(
        default=False,
        description="Automatically apply build plans without approval"
    )
    notify_on_build: bool = Field(
        default=True,
        description="Send notification when build completes"
    )
    notify_on_execution: bool = Field(
        default=True,
        description="Send notification when execution completes"
    )


class InterventionRequest(BaseModel):
    """
    Request for Developer Team intervention on a blocked challenge.

    Per CONTEXT.md: Full context provided - challenge text, assessment,
    gaps, similar past attempts, and topology snapshot.
    """
    model_config = ConfigDict(frozen=True)

    challenge_text: str = Field(
        ...,
        min_length=10,
        max_length=10000,
        description="The challenge that is blocked"
    )
    execution_id: str = Field(
        ...,
        description="Correlation ID for tracking"
    )
    project_id: str = Field(
        ...,
        description="Project ID for SharedMemory integration"
    )
    assessment: CapabilityAssessment = Field(
        ...,
        description="Phase 9 capability assessment result"
    )
    gaps: list[CapabilityGap] = Field(
        ...,
        description="Identified capability gaps from assessment"
    )


class BuildResult(BaseModel):
    """
    Result from Developer Team capability building attempt.

    Tracks success/failure, artifact metadata, and approach used.
    """
    success: bool = Field(
        ...,
        description="Whether capability was built successfully"
    )
    artifact_id: Optional[str] = Field(
        default=None,
        description="ID of the built artifact (skill, prompt, or agent)"
    )
    artifact_type: Literal["skill", "prompt", "agent"] = Field(
        ...,
        description="Type of artifact built"
    )
    failure_reason: Optional[str] = Field(
        default=None,
        description="Reason for build failure if not successful"
    )
    approach_used: str = Field(
        ...,
        description="Approach used: direct, simplified, alternative, minimal, fallback"
    )
    duration_seconds: float = Field(
        ...,
        ge=0,
        description="How long the build took"
    )
    bound_to_agent_id: Optional[str] = Field(
        default=None,
        description="ID of agent whose capabilities were expanded to include this skill"
    )
    integration_plan: Optional[SkillIntegrationPlan] = Field(
        default=None,
        description="Architect's integration plan for skill placement"
    )


class InterventionResponse(BaseModel):
    """
    Response after intervention attempt.

    Contains status, routing decision, built capabilities, and next steps.
    """
    challenge_id: str = Field(
        ...,
        description="ID of the blocked challenge"
    )
    status: ChallengeStatus = Field(
        ...,
        description="Current status of the challenge"
    )
    route_decision: Literal["execute", "still_blocked", "failed", "new_cycle", "no_gaps"] = Field(
        ...,
        description="Next action: execute (CAN_DO), still_blocked (retry), failed (max attempts), new_cycle (starting next cycle), no_gaps (no gaps to build)"
    )
    built_capabilities: list[BuildResult] = Field(
        default_factory=list,
        description="Capabilities built during this intervention"
    )
    attempt_number: int = Field(
        ...,
        ge=1,
        description="Current attempt number (1-5)"
    )
    message: str = Field(
        ...,
        description="Human-readable message about intervention result"
    )


class BlockedChallengeCreate(BaseModel):
    """
    Schema for creating a blocked challenge in the database.

    Minimal fields required for DB insertion - other fields have defaults.
    """
    execution_id: str = Field(
        ...,
        description="Correlation ID for tracking"
    )
    project_id: str = Field(
        ...,
        description="Project ID for SharedMemory integration"
    )
    challenge_text: str = Field(
        ...,
        min_length=10,
        max_length=10000,
        description="The challenge that is blocked"
    )
    assessment_result: dict = Field(
        ...,
        description="Full CapabilityAssessment dict from Phase 9"
    )
    gaps_snapshot: list[dict] = Field(
        ...,
        description="List of gap dicts at detection time"
    )


class BlockedChallengeResponse(BaseModel):
    """
    Schema for blocked challenge API responses.

    Maps directly from database model with from_attributes enabled.
    """
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="UUID primary key")
    execution_id: str = Field(..., description="Correlation ID for tracking")
    project_id: str = Field(..., description="Project ID")
    challenge_text: str = Field(..., description="The challenge that is blocked")
    assessment_result: dict = Field(
        ...,
        description="Full CapabilityAssessment dict from Phase 9"
    )
    gaps_snapshot: list[dict] = Field(
        ...,
        description="List of gap dicts at detection time"
    )
    status: str = Field(..., description="Current status")
    attempt_number: int = Field(..., description="Current attempt number")
    max_attempts: int = Field(..., description="Maximum retry attempts allowed")
    built_capability_ids: list = Field(
        ...,
        description="IDs of capabilities built for this challenge"
    )
    created_at: datetime = Field(..., description="When challenge was queued")
    updated_at: Optional[datetime] = Field(
        None,
        description="Last status update"
    )
    resolved_at: Optional[datetime] = Field(
        None,
        description="When challenge was resolved"
    )
    failure_reasons: list = Field(
        ...,
        description="List of failure messages per attempt"
    )
