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
    change_type = Column(String(50), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(36), nullable=False)
    entity_name = Column(String(255), nullable=True)
    source = Column(String(50), nullable=False)
    triggered_by = Column(String(100), nullable=True)
    change_details = Column(JSON, nullable=True)
    previous_state = Column(JSON, nullable=True)
    new_state = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index('ix_topology_change_entity', 'entity_type', 'entity_id'),
        Index('ix_topology_change_type', 'change_type'),
        Index('ix_topology_change_created', 'created_at'),
    )
