import uuid
from sqlalchemy import Column, String, Integer, DateTime, Index

from app.models.sql.base import Base


class OrchestrationTelemetry(Base):
    """
    Token-Tracking aufgeschlüsselt nach Orchestrator-Phase.

    Pro Execution genau ein Record. Wird am Ende von
    HybridOrchestrator.execute() geschrieben (single INSERT).
    """
    __tablename__ = "orchestration_telemetry"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    execution_id = Column(String(36), nullable=False, index=True, unique=True)

    tokens_assembly = Column(Integer, default=0)
    tokens_execution = Column(Integer, default=0)
    tokens_verification = Column(Integer, default=0)
    tokens_adapt = Column(Integer, default=0)
    tokens_self_healing = Column(Integer, default=0)
    tokens_total = Column(Integer, default=0)

    adapt_rounds = Column(Integer, default=0)
    verification_score = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_orch_telemetry_created", "created_at"),
    )
