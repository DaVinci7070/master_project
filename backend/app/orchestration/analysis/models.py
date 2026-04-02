"""
Internal data models for pre-execution analysis pipeline.

These models pass context between analysis stages without being exposed in API.
They support capability matching, topology inspection, and assessment context tracking.
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class CapabilityType(str, Enum):
    """
    Distinguishes knowledge capabilities from execution capabilities.

    KNOWLEDGE: Reasoning, analysis, summarization — served by LLM prompts.
    EXECUTION: Code execution, file creation, database operations — requires tools/skills.
    """
    KNOWLEDGE = "knowledge"
    EXECUTION = "execution"


class FeasibilityResult(BaseModel):
    """Result of LLM feasibility verification for an execution-type capability."""
    model_config = ConfigDict(frozen=True)

    required_capability: str
    matched_agent_id: Optional[str] = None
    feasible: bool = False
    tool_name: Optional[str] = None
    reason: str = ""


class CapabilityMatch(BaseModel):
    """
    Result of matching a required capability against topology capabilities.

    Frozen to prevent accidental modification during pipeline execution.
    Tracks semantic similarity between what's needed and what's available.
    """
    model_config = ConfigDict(frozen=True)

    required_capability: str = Field(
        ...,
        description="What the challenge needs"
    )
    capability_type: CapabilityType = Field(
        default=CapabilityType.KNOWLEDGE,
        description="Whether this capability requires execution (code/tools) or knowledge (reasoning)"
    )
    matched_capability: Optional[str] = Field(
        default=None,
        description="What the topology provides, if any match found"
    )
    similarity_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Semantic similarity score between 0.0 and 1.0"
    )
    matched_agent_id: Optional[str] = Field(
        default=None,
        description="Agent that provides the matched capability"
    )
    is_sufficient: bool = Field(
        default=False,
        description="True if similarity_score meets threshold for use"
    )


class TopologyCapabilities(BaseModel):
    """
    Snapshot of current topology capabilities for assessment.

    Extracted from TopologyLoader for analysis without coupling to loader internals.
    """
    agent_capabilities: dict[str, list[str]] = Field(
        ...,
        description="Mapping of agent_id to list of capabilities"
    )
    all_capabilities: set[str] = Field(
        ...,
        description="Flat set of all available capabilities across agents"
    )
    active_agent_count: int = Field(
        ...,
        ge=0,
        description="Number of active agents in topology"
    )
    skill_count: int = Field(
        ...,
        ge=0,
        description="Total number of skills across all agents"
    )
    has_dependency_issues: bool = Field(
        default=False,
        description="True if any dependency issues detected"
    )
    dependency_issues: list[str] = Field(
        default_factory=list,
        description="List of dependency issue descriptions"
    )


class AssessmentContext(BaseModel):
    """
    Context accumulated during assessment pipeline execution.

    Passed between analysis stages to avoid repeated lookups.
    Contains all information needed to produce final CapabilityAssessment.
    """
    challenge_text: str = Field(
        ...,
        description="The challenge being assessed"
    )
    execution_id: str = Field(
        ...,
        description="Correlation ID for tracing"
    )
    project_id: str = Field(
        ...,
        description="Project ID for SharedMemory lookups"
    )
    required_capabilities: list[str] = Field(
        default_factory=list,
        description="Capabilities extracted from challenge"
    )
    capability_matches: list[CapabilityMatch] = Field(
        default_factory=list,
        description="Results of matching required vs available capabilities"
    )
    topology_capabilities: Optional[TopologyCapabilities] = Field(
        default=None,
        description="Snapshot of current topology capabilities"
    )
    similar_successes: list[dict] = Field(
        default_factory=list,
        description="Past successful challenges from SharedMemory"
    )
    confidence_boost: float = Field(
        default=0.0,
        ge=0.0,
        description="Confidence boost from past successes"
    )
    schema_issues: list[str] = Field(
        default_factory=list,
        description="Schema mismatch issues found during analysis"
    )
    infeasible_capabilities: list[FeasibilityResult] = Field(
        default_factory=list,
        description="Execution capabilities that failed feasibility verification"
    )
