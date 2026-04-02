"""
Agent execution event models for real-time timeline streaming.

Stores agent start/complete/error events for SSE delivery.
"""
import uuid
from sqlalchemy import Column, String, Integer, Text, JSON, DateTime, Index
from sqlalchemy.sql import func

from app.models.sql.base import Base


class AgentExecutionEvent(Base):
    """
    Event queue entry for real-time agent execution updates.

    Events are created by HybridOrchestrator during execution and
    consumed by SSE endpoint for live timeline updates.

    Event types:
    - agent_start: Agent began execution
    - agent_complete: Agent finished successfully
    - agent_error: Agent execution failed
    """
    __tablename__ = "agent_execution_events"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="UUID primary key"
    )

    execution_id = Column(
        String(36),
        nullable=False,
        index=True,
        doc="Execution session ID"
    )

    agent_id = Column(
        String(36),
        nullable=False,
        doc="Agent UUID that generated this event"
    )

    agent_name = Column(
        String(255),
        nullable=True,
        doc="Human-readable agent name"
    )

    event_type = Column(
        String(50),
        nullable=False,
        doc="Event type: agent_start, agent_complete, agent_error"
    )

    wave = Column(
        Integer,
        nullable=True,
        doc="Wave number in execution sequence"
    )

    data = Column(
        JSON,
        nullable=True,
        doc="Additional event data (tokens, latency, etc.)"
    )

    error = Column(
        Text,
        nullable=True,
        doc="Error message if event_type is agent_error"
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        doc="When this event was created"
    )

    __table_args__ = (
        Index('ix_agent_events_execution_time', 'execution_id', 'created_at'),
    )

    def __repr__(self) -> str:
        return (
            f"<AgentExecutionEvent("
            f"id={self.id!r}, "
            f"execution_id={self.execution_id!r}, "
            f"agent_name={self.agent_name!r}, "
            f"event_type={self.event_type!r}"
            f")>"
        )
