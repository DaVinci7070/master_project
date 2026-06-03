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

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="UUID primary key"
    )

    execution_telemetry_id = Column(
        String(36),
        ForeignKey("execution_telemetry.id"),
        nullable=False,
        doc="UUID of the execution this finding relates to"
    )

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

    priority_rank = Column(
        Integer,
        nullable=True,
        doc="Priority rank set by Product Owner (lower = higher priority)"
    )

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

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        doc="When the finding was created"
    )

    __table_args__ = (
        Index('ix_finding_execution', 'execution_telemetry_id'),
        Index('ix_finding_category_severity', 'category', 'severity'),
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
