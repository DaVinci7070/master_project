from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class AgentStatus(str, Enum):
    """Status of a spawned agent."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentContext(BaseModel):
    """
    Isolated context for a spawned coding agent.

    Each agent receives only the information it needs to complete its task,
    following the Parallel Context Isolation (PCI) pattern.
    """
    file_path: str = Field(
        ...,
        description="Primary file this agent is responsible for"
    )
    dependencies: List[str] = Field(
        default_factory=list,
        description="File paths this agent may read (not entire context)"
    )
    interface_contract: Dict[str, Any] = Field(
        default_factory=dict,
        description="Expected input/output schema for the generated code"
    )
    parent_task_id: str = Field(
        ...,
        description="UUID of parent DevelopmentTask for tracing"
    )
    additional_context: str = Field(
        default="",
        max_length=10000,
        description="Additional context or instructions for the agent"
    )


class SubtaskSpec(BaseModel):
    """
    Specification for a subtask to be handled by a spawned agent.

    Created by task decomposition, executed by individual agents.
    """
    file_path: str = Field(
        ...,
        description="File to create or modify"
    )
    task_description: str = Field(
        ...,
        min_length=10,
        description="What this subtask accomplishes"
    )
    required_files: List[str] = Field(
        default_factory=list,
        description="Files this subtask needs to read"
    )
    interface_contract: Dict[str, Any] = Field(
        default_factory=dict,
        description="Schema contract for generated code"
    )
    estimated_complexity: Literal["simple", "moderate", "complex"] = Field(
        default="moderate",
        description="Estimated task complexity"
    )
    depends_on: List[str] = Field(
        default_factory=list,
        description="File paths that must be completed first"
    )


class DevelopmentTask(BaseModel):
    """
    A complex development task that may require multiple agents.

    Input to the DeveloperTeamOrchestrator for decomposition and execution.
    """
    task_id: str = Field(
        ...,
        min_length=36,
        max_length=36,
        description="UUID for this task"
    )
    description: str = Field(
        ...,
        min_length=20,
        description="Natural language description of what to build"
    )
    files_involved: List[str] = Field(
        ...,
        min_length=1,
        description="Files that will be created or modified"
    )
    context_files: List[str] = Field(
        default_factory=list,
        description="Existing files to reference (read-only)"
    )
    constraints: List[str] = Field(
        default_factory=list,
        description="Requirements or limitations"
    )
    improvement_attempt_id: Optional[str] = Field(
        None,
        description="Link to improvement attempt if triggered by analysis"
    )

    @field_validator('files_involved')
    @classmethod
    def validate_files(cls, v: List[str]) -> List[str]:
        """Ensure reasonable number of files (prevent runaway spawning)."""
        if len(v) > 10:
            raise ValueError("Cannot involve more than 10 files (max spawn limit)")
        return v


class TaskDecomposition(BaseModel):
    """
    Result of decomposing a DevelopmentTask into subtasks.

    Produced by LLM analysis, consumed by orchestrator for spawning.
    """
    task_id: str = Field(
        ...,
        description="UUID of the original DevelopmentTask"
    )
    subtasks: List[SubtaskSpec] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="Subtasks to execute (max 10)"
    )
    execution_order: List[List[str]] = Field(
        ...,
        description="Parallel execution waves (list of file path lists)"
    )
    shared_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Context shared across all subtasks"
    )
    rationale: str = Field(
        ...,
        min_length=20,
        description="Why this decomposition strategy was chosen"
    )


class SpawnRequest(BaseModel):
    """
    Request to spawn a new coding agent.

    Submitted to AgentSpawnerService by the orchestrator.
    """
    task_id: str = Field(
        ...,
        description="Parent task UUID"
    )
    subtask: SubtaskSpec = Field(
        ...,
        description="The subtask for this agent to execute"
    )
    context: AgentContext = Field(
        ...,
        description="Isolated context for the agent"
    )
    timeout_seconds: int = Field(
        default=300,
        ge=30,
        le=600,
        description="Max execution time (30s-10min)"
    )
    memory_limit_mb: int = Field(
        default=512,
        ge=128,
        le=2048,
        description="Memory limit for subprocess (128MB-2GB)"
    )


class SpawnedAgent(BaseModel):
    """
    Metadata for a spawned coding agent.

    Stored in RuntimeAgentRegistry for tracking and cleanup.
    """
    agent_id: str = Field(
        ...,
        min_length=36,
        max_length=36,
        description="Unique UUID for this spawned agent"
    )
    task_id: str = Field(
        ...,
        description="Parent task UUID"
    )
    file_path: str = Field(
        ...,
        description="File this agent is working on"
    )
    status: AgentStatus = Field(
        default=AgentStatus.PENDING,
        description="Current agent status"
    )
    spawned_at: datetime = Field(
        ...,
        description="When the agent was spawned"
    )
    completed_at: Optional[datetime] = Field(
        None,
        description="When the agent finished"
    )
    process_id: Optional[int] = Field(
        None,
        description="OS process ID for subprocess"
    )
    trace_id: Optional[str] = Field(
        None,
        description="OpenTelemetry trace ID for correlation"
    )
    span_id: Optional[str] = Field(
        None,
        description="OpenTelemetry span ID"
    )


class SpawnResult(BaseModel):
    """
    Result from a spawned agent's execution.

    Returned by AgentSpawnerService after agent completes.
    """
    agent_id: str = Field(
        ...,
        description="ID of the spawned agent"
    )
    success: bool = Field(
        ...,
        description="Whether the agent completed successfully"
    )
    file_path: str = Field(
        ...,
        description="File that was created/modified"
    )
    generated_code: Optional[str] = Field(
        None,
        description="Code generated by the agent"
    )
    error_message: Optional[str] = Field(
        None,
        description="Error details if failed"
    )
    duration_seconds: float = Field(
        ...,
        description="Execution duration"
    )
    tokens_used: int = Field(
        default=0,
        description="LLM tokens consumed"
    )
    stdout: str = Field(
        default="",
        description="Agent stdout output"
    )
    stderr: str = Field(
        default="",
        description="Agent stderr output"
    )


class CodingAgentOutput(BaseModel):
    """
    Structured output from a coding agent LLM call.

    Used with Instructor to ensure valid, parseable responses.
    """
    code: str = Field(
        ...,
        description="Complete Python code for the file"
    )
    imports: List[str] = Field(
        default_factory=list,
        description="List of imports used in the code"
    )
    rationale: str = Field(
        default="",
        description="Why this implementation approach was chosen"
    )
    assumptions: List[str] = Field(
        default_factory=list,
        description="Assumptions made about interfaces or requirements"
    )
    tests_suggested: List[str] = Field(
        default_factory=list,
        description="Test cases that should exist for this code"
    )


class TaskDecompositionOutput(BaseModel):
    """
    Structured output from task decomposition LLM call.

    Used with Instructor to ensure valid decomposition.
    """
    subtasks: List[SubtaskSpec] = Field(
        ...,
        description="List of subtasks to execute"
    )
    execution_waves: List[List[str]] = Field(
        ...,
        description="Parallel execution waves (list of file paths per wave)"
    )
    shared_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Context shared across all subtasks"
    )
    rationale: str = Field(
        default="",
        description="Why this decomposition strategy was chosen"
    )
