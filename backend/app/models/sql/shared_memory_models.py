import uuid
from sqlalchemy import Column, String, Text, JSON, Float, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship

from app.models.sql.base import Base


class Fact(Base):
    """
    A fact represents an observation with a confidence score.

    Facts are the atomic units of shared memory, storing observations
    from agent executions with confidence levels and metadata.
    """
    __tablename__ = "facts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    text = Column(Text, nullable=False)
    confidence = Column(Float, nullable=False)
    source_agent_id = Column(String(255), nullable=False)
    execution_id = Column(String(36), nullable=False)
    project_id = Column(String(36), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    tags = Column(JSON, default=list)
    supersedes_id = Column(String(36), ForeignKey("facts.id"), nullable=True)
    embedding_id = Column(String(255), nullable=True)

    supersedes = relationship("Fact", remote_side=[id], backref="superseded_by")

    caused_relations = relationship(
        "Relation",
        foreign_keys="Relation.source_fact_id",
        back_populates="source_fact"
    )
    effect_relations = relationship(
        "Relation",
        foreign_keys="Relation.target_fact_id",
        back_populates="target_fact"
    )


class Hypothesis(Base):
    """
    A hypothesis represents a system learning or theory.

    Hypotheses can be linked to supporting or contradicting facts,
    enabling automatic contradiction detection and confirmation.
    """
    __tablename__ = "hypotheses"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    text = Column(Text, nullable=False)
    confidence = Column(Float, nullable=False)
    source_agent_id = Column(String(255), nullable=False)
    execution_id = Column(String(36), nullable=False)
    project_id = Column(String(36), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String(20), default="active")
    supporting_fact_ids = Column(JSON, default=list)
    contradicting_fact_ids = Column(JSON, default=list)


class Relation(Base):
    """
    A relation represents a causal chain between facts.

    Relations track simple "A caused B" relationships, enabling
    reasoning about cause-and-effect chains in agent observations.
    """
    __tablename__ = "relations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    relation_type = Column(String(20), nullable=False)
    source_fact_id = Column(String(36), ForeignKey("facts.id"), nullable=False)
    target_fact_id = Column(String(36), ForeignKey("facts.id"), nullable=False)
    confidence = Column(Float, nullable=False)
    source_agent_id = Column(String(255), nullable=False)
    execution_id = Column(String(36), nullable=False)
    project_id = Column(String(36), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    source_fact = relationship(
        "Fact",
        foreign_keys=[source_fact_id],
        back_populates="caused_relations"
    )
    target_fact = relationship(
        "Fact",
        foreign_keys=[target_fact_id],
        back_populates="effect_relations"
    )
