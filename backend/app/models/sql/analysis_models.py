"""
Analysis models for storing agent analysis findings.

This module implements AnalysisFinding model for persisting analysis results
that identify issues in agent executions. Findings are append-only artifacts
linked to ExecutionTelemetry records.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Text, DateTime, ForeignKey, Index
)
from app.models.sql.base import Base


class AnalysisFinding(Base):
    """
    Analysis finding record linked to an execution.

    Findings capture issues identified during analysis of agent executions:
    - category: Type of issue (prompt, topology, skill, error)
    - severity: Impact level (critical, warning, info)
    - evidence: Telemetry data supporting the finding
    - suggested_fix: Hypothesis for resolution

    Findings are append-only - they represent historical analysis artifacts.
    """
    __tablename__ = "analysis_finding"

    # Primary key
    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="UUID primary key"
    )

    # Foreign key to execution telemetry
    execution_telemetry_id = Column(
        String(36),
        ForeignKey("execution_telemetry.id"),
        nullable=False,
        doc="UUID of the execution this finding relates to"
    )

    # Finding classification
    category = Column(
        String(32),
        nullable=False,
        doc="Finding category: prompt, topology, skill, error"
    )
    severity = Column(
        String(16),
        nullable=False,
        doc="Finding severity: critical, warning, info"
    )

    # Finding content
    evidence = Column(
        Text,
        nullable=False,
        doc="Telemetry data supporting this finding"
    )
    suggested_fix = Column(
        Text,
        nullable=False,
        doc="Hypothesis for what could resolve the issue"
    )

    # Priority (set by Product Owner agent)
    priority_rank = Column(
        Integer,
        nullable=True,
        doc="Priority rank set by Product Owner (lower = higher priority)"
    )

    # Execution context snapshots
    input_content = Column(
        Text,
        nullable=True,
        doc="Snapshot of execution input for context"
    )
    output_content = Column(
        Text,
        nullable=True,
        doc="Snapshot of execution output for context"
    )

    # Timestamp
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="When the finding was created"
    )

    # Indexes for common query patterns
    __table_args__ = (
        # Filter findings by execution
        Index('ix_finding_execution', 'execution_telemetry_id'),
        # Pattern queries by category and severity
        Index('ix_finding_category_severity', 'category', 'severity'),
        # Time-series queries
        Index('ix_finding_created', 'created_at'),
    )

    def __repr__(self) -> str:
        return (
            f"<AnalysisFinding("
            f"id={self.id!r}, "
            f"category={self.category!r}, "
            f"severity={self.severity!r}"
            f")>"
        )
