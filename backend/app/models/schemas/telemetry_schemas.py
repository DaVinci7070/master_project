from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field, ConfigDict


OutcomeType = Literal["success", "error", "timeout", "cancelled", "running"]


class ExecutionTelemetryCreate(BaseModel):
    """
    Schema for creating a new telemetry record.

    Used when an agent execution starts. Only required fields
    must be provided; execution completion fields are optional.
    """
    agent_id: str = Field(
        ...,
        min_length=36,
        max_length=36,
        description="UUID of the agent that is executing"
    )
    execution_id: str = Field(
        ...,
        min_length=36,
        max_length=36,
        description="UUID of this specific execution instance"
    )
    started_at: datetime = Field(
        ...,
        description="When execution started (timezone-aware)"
    )
    input_hash: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="SHA-256 hash of input for deduplication"
    )
    outcome: OutcomeType = Field(
        ...,
        description="Initial execution outcome"
    )

    trace_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="OpenTelemetry trace ID"
    )
    span_id: Optional[str] = Field(
        default=None,
        max_length=32,
        description="OpenTelemetry span ID"
    )
    execution_metadata: Optional[dict] = Field(
        default_factory=dict,
        description="Additional execution metadata"
    )


class ExecutionTelemetryUpdate(BaseModel):
    """
    Schema for updating a telemetry record when execution completes.

    All fields are optional since different updates may provide
    different subsets of completion data.
    """
    completed_at: Optional[datetime] = Field(
        default=None,
        description="When execution completed"
    )
    latency_ms: Optional[float] = Field(
        default=None,
        ge=0,
        description="Total execution time in milliseconds"
    )
    tokens_input: Optional[int] = Field(
        default=None,
        ge=0,
        description="Number of input tokens consumed"
    )
    tokens_output: Optional[int] = Field(
        default=None,
        ge=0,
        description="Number of output tokens generated"
    )
    tokens_total: Optional[int] = Field(
        default=None,
        ge=0,
        description="Total tokens (input + output)"
    )
    output_hash: Optional[str] = Field(
        default=None,
        min_length=64,
        max_length=64,
        description="SHA-256 hash of output for deduplication"
    )
    outcome: Optional[OutcomeType] = Field(
        default=None,
        description="Final execution outcome"
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error message if outcome is error"
    )
    error_type: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Error type/class name if outcome is error"
    )
    execution_metadata: Optional[dict] = Field(
        default=None,
        description="Updated execution metadata"
    )


class ExecutionTelemetryResponse(BaseModel):
    """
    Schema for telemetry record API responses.

    Includes all fields from the database model for complete
    visibility into execution metrics.
    """
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="UUID primary key")
    agent_id: str = Field(..., description="UUID of the agent that executed")
    execution_id: str = Field(..., description="UUID of this execution instance")
    started_at: datetime = Field(..., description="When execution started")
    completed_at: Optional[datetime] = Field(None, description="When execution completed")
    latency_ms: Optional[float] = Field(None, description="Execution time in milliseconds")

    tokens_input: int = Field(default=0, description="Input tokens consumed")
    tokens_output: int = Field(default=0, description="Output tokens generated")
    tokens_total: int = Field(default=0, description="Total tokens used")

    input_hash: str = Field(..., description="SHA-256 hash of input")
    output_hash: Optional[str] = Field(None, description="SHA-256 hash of output")

    outcome: OutcomeType = Field(..., description="Execution outcome")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    error_type: Optional[str] = Field(None, description="Error type if failed")

    trace_id: Optional[str] = Field(None, description="OpenTelemetry trace ID")
    span_id: Optional[str] = Field(None, description="OpenTelemetry span ID")

    execution_metadata: dict = Field(default_factory=dict, description="Additional metadata")


class TelemetryAggregation(BaseModel):
    """
    Aggregated telemetry metrics for dashboard queries.

    Used for displaying agent performance over time periods.
    """
    agent_id: str = Field(..., description="UUID of the agent")
    total_executions: int = Field(..., ge=0, description="Total number of executions")
    successful_executions: int = Field(..., ge=0, description="Number of successful executions")
    failed_executions: int = Field(..., ge=0, description="Number of failed executions")
    timeout_executions: int = Field(default=0, ge=0, description="Number of timed out executions")
    cancelled_executions: int = Field(default=0, ge=0, description="Number of cancelled executions")

    success_rate: float = Field(
        ...,
        ge=0,
        le=100,
        description="Success rate as percentage"
    )

    avg_latency_ms: Optional[float] = Field(
        None,
        ge=0,
        description="Average latency in milliseconds"
    )
    min_latency_ms: Optional[float] = Field(
        None,
        ge=0,
        description="Minimum latency in milliseconds"
    )
    max_latency_ms: Optional[float] = Field(
        None,
        ge=0,
        description="Maximum latency in milliseconds"
    )
    p50_latency_ms: Optional[float] = Field(
        None,
        ge=0,
        description="50th percentile (median) latency"
    )
    p95_latency_ms: Optional[float] = Field(
        None,
        ge=0,
        description="95th percentile latency"
    )
    p99_latency_ms: Optional[float] = Field(
        None,
        ge=0,
        description="99th percentile latency"
    )

    total_tokens_input: int = Field(default=0, ge=0, description="Total input tokens")
    total_tokens_output: int = Field(default=0, ge=0, description="Total output tokens")
    total_tokens: int = Field(default=0, ge=0, description="Total tokens used")
    avg_tokens_per_execution: Optional[float] = Field(
        None,
        ge=0,
        description="Average tokens per execution"
    )

    period_start: Optional[datetime] = Field(None, description="Start of aggregation period")
    period_end: Optional[datetime] = Field(None, description="End of aggregation period")


class TelemetrySummary(BaseModel):
    """
    Quick summary statistics for telemetry overview.

    Lightweight schema for quick health checks and status displays.
    """
    total_executions: int = Field(..., ge=0, description="Total executions recorded")
    executions_last_hour: int = Field(default=0, ge=0, description="Executions in last hour")
    executions_last_24h: int = Field(default=0, ge=0, description="Executions in last 24 hours")

    success_rate_overall: float = Field(
        ...,
        ge=0,
        le=100,
        description="Overall success rate as percentage"
    )
    success_rate_last_hour: Optional[float] = Field(
        None,
        ge=0,
        le=100,
        description="Success rate in last hour"
    )

    avg_latency_ms: Optional[float] = Field(
        None,
        ge=0,
        description="Average latency across all executions"
    )
    avg_latency_last_hour: Optional[float] = Field(
        None,
        ge=0,
        description="Average latency in last hour"
    )

    total_tokens_consumed: int = Field(default=0, ge=0, description="Total tokens ever used")
    tokens_last_hour: int = Field(default=0, ge=0, description="Tokens used in last hour")

    unique_agents: int = Field(default=0, ge=0, description="Number of unique agents with telemetry")
    most_active_agent_id: Optional[str] = Field(None, description="Agent with most executions")

    last_execution_at: Optional[datetime] = Field(None, description="Most recent execution time")
