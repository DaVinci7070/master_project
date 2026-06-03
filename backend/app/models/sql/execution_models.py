import uuid
from sqlalchemy import Column, String, Integer, Text, JSON, DateTime, Index
from sqlalchemy.sql import func

from app.models.sql.base import Base


class Execution(Base):
    """
    Persistent execution record for history tracking.

    Created at execution start, updated on completion with results.
    Enables execution history view and post-navigation access.

    Status lifecycle: pending -> running -> completed/failed
    """
    __tablename__ = "executions"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Execution ID (same as used throughout orchestration)"
    )

    challenge_id = Column(
        String(36),
        nullable=True,
        index=True,
        doc="Associated challenge ID if from challenge execution"
    )

    project_id = Column(
        String(36),
        nullable=False,
        index=True,
        doc="Project scope for this execution"
    )

    status = Column(
        String(50),
        nullable=False,
        default="pending",
        index=True,
        doc="Execution status: pending, running, completed, failed"
    )

    input_data = Column(
        JSON,
        nullable=True,
        doc="Input data passed to execution"
    )

    results = Column(
        JSON,
        nullable=True,
        doc="Full execution results (wave outputs, agent results)"
    )

    agents_executed = Column(
        Integer,
        default=0,
        doc="Total number of agents that executed"
    )

    waves_executed = Column(
        Integer,
        default=0,
        doc="Number of waves completed"
    )

    duration_ms = Column(
        Integer,
        nullable=True,
        doc="Total execution duration in milliseconds"
    )

    error = Column(
        Text,
        nullable=True,
        doc="Error message if status is failed"
    )

    started_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        doc="When execution started"
    )

    completed_at = Column(
        DateTime(timezone=True),
        nullable=True,
        doc="When execution completed or failed"
    )

    __table_args__ = (
        Index('ix_executions_started_at', 'started_at'),
    )

    def __repr__(self) -> str:
        return (
            f"<Execution("
            f"id={self.id!r}, "
            f"status={self.status!r}, "
            f"agents_executed={self.agents_executed}"
            f")>"
        )
