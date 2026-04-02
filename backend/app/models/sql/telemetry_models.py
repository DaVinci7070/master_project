"""
Telemetry models for logging agent execution metrics.

This module implements DB-07 (execution telemetry) and DB-08 (input/output hashing)
requirements. ExecutionTelemetry is append-only (no versioning) for audit trail.
"""
import uuid
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Text, JSON, Index
)
from app.models.sql.base import Base


class ExecutionTelemetry(Base):
    """
    Append-only telemetry record for agent executions.

    Every agent execution is logged with:
    - Timing metrics (started_at, completed_at, latency_ms)
    - Token counts (input, output, total)
    - Input/output hashes for deduplication (DB-08)
    - Outcome and error details
    - Distributed tracing IDs (trace_id, span_id)
    """
    __tablename__ = "execution_telemetry"

    # Primary key
    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="UUID primary key"
    )

    # Agent and execution identification
    agent_id = Column(
        String(36),
        nullable=False,
        index=True,
        doc="UUID of the agent that executed"
    )
    execution_id = Column(
        String(36),
        nullable=False,
        index=True,
        doc="UUID of this specific execution instance"
    )

    # Timing
    started_at = Column(
        DateTime(timezone=True),
        nullable=False,
        doc="When execution started (timezone-aware)"
    )
    completed_at = Column(
        DateTime(timezone=True),
        nullable=True,
        doc="When execution completed (null if still running or crashed)"
    )
    latency_ms = Column(
        Float,
        nullable=True,
        doc="Total execution time in milliseconds"
    )

    # Token usage
    tokens_input = Column(
        Integer,
        default=0,
        nullable=False,
        doc="Number of input tokens consumed"
    )
    tokens_output = Column(
        Integer,
        default=0,
        nullable=False,
        doc="Number of output tokens generated"
    )
    tokens_total = Column(
        Integer,
        default=0,
        nullable=False,
        doc="Total tokens (input + output)"
    )

    # Input/output hashing for deduplication (DB-08)
    input_hash = Column(
        String(64),
        nullable=False,
        index=True,
        doc="SHA-256 hash of input for deduplication"
    )
    output_hash = Column(
        String(64),
        nullable=True,
        index=True,
        doc="SHA-256 hash of output for deduplication"
    )

    # Outcome
    outcome = Column(
        String(32),
        nullable=False,
        doc="Execution outcome: success, error, timeout, cancelled"
    )
    error_message = Column(
        Text,
        nullable=True,
        doc="Error message if outcome is error"
    )
    error_type = Column(
        String(128),
        nullable=True,
        doc="Error type/class name if outcome is error"
    )

    # Distributed tracing
    trace_id = Column(
        String(64),
        nullable=True,
        doc="OpenTelemetry trace ID for distributed tracing"
    )
    span_id = Column(
        String(32),
        nullable=True,
        doc="OpenTelemetry span ID for distributed tracing"
    )

    # Flexible metadata
    execution_metadata = Column(
        JSON,
        default=dict,
        nullable=False,
        doc="Additional execution metadata as JSON"
    )

    # Composite indexes for common query patterns
    __table_args__ = (
        # Time-series queries: get executions for an agent over time
        Index('ix_telemetry_agent_time', 'agent_id', 'started_at'),
        # Deduplication queries: find executions with same input/output
        Index('ix_telemetry_hash_dedup', 'input_hash', 'output_hash'),
    )

    def __repr__(self) -> str:
        return (
            f"<ExecutionTelemetry("
            f"id={self.id!r}, "
            f"agent_id={self.agent_id!r}, "
            f"outcome={self.outcome!r}, "
            f"latency_ms={self.latency_ms}"
            f")>"
        )
