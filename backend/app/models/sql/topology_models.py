"""
SQLAlchemy models for topology change tracking.

Provides audit trail for all topology modifications.
"""
import uuid
from sqlalchemy import Column, String, JSON, DateTime, func, Index

from app.models.sql.base import Base


class TopologyChangeLog(Base):
    """
    Log of all topology changes for audit and observability.

    Records agent/skill/prompt creation, updates, and deactivation.
    """
    __tablename__ = "topology_change_log"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    change_type = Column(String(50), nullable=False)  # agent_created, agent_updated, agent_deactivated, etc.
    entity_type = Column(String(50), nullable=False)  # agent, skill, prompt
    entity_id = Column(String(36), nullable=False)
    entity_name = Column(String(255), nullable=True)
    source = Column(String(50), nullable=False)  # system, manual, migration
    triggered_by = Column(String(100), nullable=True)  # challenge_id, user_id, or migration name
    change_details = Column(JSON, nullable=True)  # Additional context about the change
    previous_state = Column(JSON, nullable=True)  # State before change (for updates)
    new_state = Column(JSON, nullable=True)  # State after change
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index('ix_topology_change_entity', 'entity_type', 'entity_id'),
        Index('ix_topology_change_type', 'change_type'),
        Index('ix_topology_change_created', 'created_at'),
    )
