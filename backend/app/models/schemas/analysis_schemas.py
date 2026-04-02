"""
Pydantic schemas for analysis operations.

These schemas handle validation for:
- LLM structured output (Finding, AnalysisResult)
- Product Owner prioritization (PriorityItem, PriorityList)
- Database operations (AnalysisFindingCreate, AnalysisFindingResponse)
- Pre-execution capability assessment (ConfidenceLevel, CapabilityGap, CapabilityAssessment)
"""
from datetime import datetime
from enum import Enum
from typing import Optional, Literal

from pydantic import BaseModel, Field, ConfigDict


# Category types for findings
CategoryType = Literal["prompt", "topology", "skill", "error"]

# Severity levels for findings
SeverityType = Literal["critical", "warning", "info"]


class Finding(BaseModel):
    """
    Single finding from LLM analysis.

    Used as structured output from the analysis LLM call.
    Produces JSON Schema compatible with LLM function calling.
    """
    category: CategoryType = Field(
        ...,
        description="Type of issue: prompt, topology, skill, or error"
    )
    severity: SeverityType = Field(
        ...,
        description="Impact level: critical, warning, or info"
    )
    evidence: str = Field(
        ...,
        min_length=1,
        description="Telemetry data supporting this finding"
    )
    suggested_fix: str = Field(
        ...,
        min_length=1,
        description="Hypothesis for what could resolve the issue"
    )


class AnalysisResult(BaseModel):
    """
    Complete analysis result from LLM.

    Wraps multiple findings with execution context and summary.
    Used as the top-level structured output from analysis.
    """
    findings: list[Finding] = Field(
        default_factory=list,
        description="List of findings from analysis"
    )
    execution_id: str = Field(
        ...,
        description="UUID of the execution that was analyzed"
    )
    summary: str = Field(
        ...,
        min_length=1,
        description="Brief overview of the analysis results"
    )


class PriorityItem(BaseModel):
    """
    Priority assignment for a single finding.

    Used by Product Owner agent to rank findings.
    """
    finding_index: int = Field(
        ...,
        ge=0,
        description="Index of the finding in the findings list"
    )
    priority_rank: int = Field(
        ...,
        ge=1,
        description="Priority rank (1 = highest priority)"
    )
    rationale: str = Field(
        ...,
        min_length=1,
        description="Why this priority was assigned"
    )


class PriorityList(BaseModel):
    """
    Complete prioritization result from Product Owner.

    Contains priority assignments for all findings and
    an overall improvement direction recommendation.
    """
    priorities: list[PriorityItem] = Field(
        default_factory=list,
        description="Priority assignments for findings"
    )
    improvement_direction: str = Field(
        ...,
        min_length=1,
        description="Overall recommendation for next improvement action"
    )


class AnalysisFindingCreate(BaseModel):
    """
    Schema for creating a new analysis finding in the database.

    Validates all required fields for database insertion.
    """
    execution_telemetry_id: str = Field(
        ...,
        min_length=36,
        max_length=36,
        description="UUID of the execution this finding relates to"
    )
    category: CategoryType = Field(
        ...,
        description="Finding category: prompt, topology, skill, error"
    )
    severity: SeverityType = Field(
        ...,
        description="Finding severity: critical, warning, info"
    )
    evidence: str = Field(
        ...,
        min_length=1,
        description="Telemetry data supporting this finding"
    )
    suggested_fix: str = Field(
        ...,
        min_length=1,
        description="Hypothesis for what could resolve the issue"
    )
    priority_rank: Optional[int] = Field(
        default=None,
        ge=1,
        description="Priority rank set by Product Owner (lower = higher priority)"
    )
    input_content: Optional[str] = Field(
        default=None,
        description="Snapshot of execution input for context"
    )
    output_content: Optional[str] = Field(
        default=None,
        description="Snapshot of execution output for context"
    )


class AnalysisFindingResponse(BaseModel):
    """
    Schema for analysis finding API responses.

    Maps directly from database model with from_attributes enabled.
    """
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="UUID primary key")
    execution_telemetry_id: str = Field(
        ...,
        description="UUID of the execution this finding relates to"
    )
    category: str = Field(..., description="Finding category")
    severity: str = Field(..., description="Finding severity")
    evidence: str = Field(..., description="Telemetry data supporting this finding")
    suggested_fix: str = Field(..., description="Hypothesis for resolution")
    priority_rank: Optional[int] = Field(
        None,
        description="Priority rank set by Product Owner"
    )
    input_content: Optional[str] = Field(
        None,
        description="Snapshot of execution input"
    )
    output_content: Optional[str] = Field(
        None,
        description="Snapshot of execution output"
    )
    created_at: datetime = Field(..., description="When the finding was created")


# =============================================================================
# Pre-Execution Capability Assessment Schemas (Phase 9)
# =============================================================================


class ConfidenceLevel(str, Enum):
    """
    Three-level confidence verdict for capability assessment.

    Per CONTEXT.md: No percentages or subscores - just these three levels.
    MAYBE and CANNOT_DO both route to Developer Team for capability building.
    """
    CAN_DO = "CAN_DO"  # All capabilities matched, proceed to execution
    MAYBE = "MAYBE"  # Partial match, route to Developer Team
    CANNOT_DO = "CANNOT_DO"  # Missing critical capabilities, route to Developer Team


class GapSeverity(str, Enum):
    """
    Impact ranking for capability gaps per CONTEXT.md.

    Used to prioritize which gaps to address first.
    """
    CRITICAL = "critical"  # Blocks execution entirely
    IMPORTANT = "important"  # Degrades quality significantly
    MINOR = "minor"  # Workaround exists


class GapType(str, Enum):
    """
    Categories of capability gaps from CONTEXT.md topology analysis.

    Covers: skills, prompts, missing agents, broken dependencies, schema mismatches.
    """
    MISSING_SKILL = "missing_skill"
    WEAK_PROMPT = "weak_prompt"
    TOPOLOGY_ISSUE = "topology_issue"
    MISSING_AGENT = "missing_agent"
    SCHEMA_MISMATCH = "schema_mismatch"


class CapabilityGap(BaseModel):
    """
    Single capability gap identified during pre-execution analysis.

    Tracks gap type, severity, and recurrence per CONTEXT.md requirement
    to identify systematic capability holes.
    """
    gap_type: GapType = Field(
        ...,
        description="Type of capability gap"
    )
    severity: GapSeverity = Field(
        ...,
        description="Impact ranking: critical, important, or minor"
    )
    description: str = Field(
        ...,
        max_length=500,
        description="Concise description of the gap"
    )
    affected_capability: str = Field(
        ...,
        description="The capability that is missing or weak"
    )
    occurrence_count: int = Field(
        default=1,
        ge=1,
        description="Recurring gap tracking - how many times this gap has blocked challenges"
    )


class CapabilityAssessment(BaseModel):
    """
    Complete capability assessment result.

    Per CONTEXT.md: Three confidence levels only, minimal reasoning (top 1-2 factors),
    improvement suggestions when confidence is low.
    """
    confidence: ConfidenceLevel = Field(
        ...,
        description="The three-level verdict: CAN_DO, MAYBE, or CANNOT_DO"
    )
    reasoning: str = Field(
        ...,
        max_length=500,
        description="Minimal reasoning for the verdict"
    )
    top_factors: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Key factors driving the confidence verdict (ideally 1-2, max 10)"
    )
    gaps: list[CapabilityGap] = Field(
        default_factory=list,
        description="Identified capability gaps"
    )
    improvement_suggestions: list[str] = Field(
        default_factory=list,
        description="Suggestions when confidence is low (e.g., 'Consider adding skill X')"
    )
    similar_past_success: bool = Field(
        default=False,
        description="Boosted by SharedMemory patterns from past successes"
    )
    challenge_embedding_id: Optional[str] = Field(
        default=None,
        description="For future similarity lookups in SharedMemory"
    )

    def should_route_to_developer(self) -> bool:
        """
        Determine if challenge should route to Developer Team.

        Per CONTEXT.md: CANNOT_DO and MAYBE both route to Developer Team
        for capability building before execution attempt.
        """
        return self.confidence in (ConfidenceLevel.CANNOT_DO, ConfidenceLevel.MAYBE)


class ChallengeAnalysisRequest(BaseModel):
    """
    Request schema for pre-execution capability analysis.

    Includes cross-project pattern support per CONTEXT.md Phase 8 integration.
    """
    challenge_text: str = Field(
        ...,
        min_length=10,
        max_length=10000,
        description="The challenge to analyze for capability assessment"
    )
    execution_id: str = Field(
        ...,
        description="Correlation ID for this analysis"
    )
    project_id: str = Field(
        ...,
        description="Project ID for SharedMemory cross-project patterns"
    )
    include_cross_project: bool = Field(
        default=True,
        description="Include cross-project patterns per CONTEXT.md"
    )


class ChallengeAnalysisResponse(BaseModel):
    """
    Response schema for pre-execution capability analysis.

    Contains assessment result and routing decision.
    """
    assessment: CapabilityAssessment = Field(
        ...,
        description="Complete capability assessment"
    )
    challenge_text: str = Field(
        ...,
        description="Truncated challenge text for response"
    )
    execution_id: str = Field(
        ...,
        description="Correlation ID for this analysis"
    )
    analyzed_at: datetime = Field(
        ...,
        description="When the analysis was performed"
    )
    route_decision: str = Field(
        ...,
        description="Routing decision: 'execute' or 'developer_team'"
    )
