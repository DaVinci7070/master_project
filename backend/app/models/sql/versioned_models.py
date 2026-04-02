"""
Versioned SQLAlchemy models for prompts, agents, and skills.

Uses SQLAlchemy-Continuum for automatic version tracking.
All models support parent-child relationships for version lineage.
"""
import uuid
from sqlalchemy import Column, String, Text, JSON, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship, configure_mappers
from sqlalchemy_continuum import make_versioned

from app.models.sql.base import Base

# Initialize versioning BEFORE defining models
make_versioned(user_cls=None)


class Prompt(Base):
    """
    Versioned prompt model for storing prompt templates.

    Supports parent-child relationships for tracking prompt evolution.
    """
    __tablename__ = "prompts"
    __versioned__ = {}

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    parent_id = Column(String(36), ForeignKey("prompts.id"), nullable=True)
    name = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    prompt_metadata = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Self-referential relationship for parent-child
    parent = relationship("Prompt", remote_side=[id], backref="children")
    # Relationship to agents using this prompt
    agents = relationship("Agent", back_populates="prompt")


class Agent(Base):
    """
    Versioned agent model for storing agent configurations.

    Agents have capabilities, dependencies, and IO schemas.
    Source tracks origin: 'initial' (migration), 'system_generated', 'manual'
    """
    __tablename__ = "agents"
    __versioned__ = {}

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False, unique=True)
    capabilities = Column(JSON, default=list)
    dependencies = Column(JSON, default=list)
    io_schema = Column(JSON, nullable=False)
    is_active = Column(Boolean, default=True)
    prompt_id = Column(String(36), ForeignKey("prompts.id"), nullable=True)
    source = Column(String(50), default='initial')  # initial, system_generated, manual
    agent_metadata = Column(JSON, default=dict)  # Additional metadata (built_by, gap_type, etc.)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship to prompt
    prompt = relationship("Prompt", back_populates="agents")


class Skill(Base):
    """
    Versioned skill model for storing executable skills/tools.

    Supports parent-child relationships for tracking skill evolution.
    Skills have test cases for validation.
    """
    __tablename__ = "skills"
    __versioned__ = {}

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    parent_id = Column(String(36), ForeignKey("skills.id"), nullable=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    code = Column(Text, nullable=False)
    test_cases = Column(JSON, default=list)
    skill_metadata = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Self-referential relationship for parent-child
    parent = relationship("Skill", remote_side=[id], backref="children")


# Configure mappers AFTER all versioned models are defined
configure_mappers()
