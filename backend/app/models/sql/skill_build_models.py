import uuid
from sqlalchemy import Column, String, Text, JSON, Boolean, DateTime, ForeignKey, Integer, Float, func
from sqlalchemy.orm import relationship

from app.models.sql.base import Base


class SkillBinding(Base):
    """
    Links skills to agents for capability matching.

    When a skill is built for a capability, it gets bound to an agent
    that should execute it. This tracks those bindings.
    """
    __tablename__ = "skill_bindings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    skill_id = Column(String(36), ForeignKey("skills.id"), nullable=False, index=True)
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=False, index=True)
    capability = Column(String(500), nullable=False)
    binding_type = Column(String(50), default="auto")
    priority = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    skill = relationship("Skill", backref="bindings")
    agent = relationship("Agent", backref="skill_bindings")


class SkillBuildAttempt(Base):
    """
    Records every skill build attempt for learning from failures.

    This enables:
    - Learning from failed approaches
    - Avoiding repeated mistakes
    - Building success/failure patterns
    """
    __tablename__ = "skill_build_attempts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    capability = Column(String(500), nullable=False, index=True)
    team_role = Column(String(50), nullable=True)

    attempt_number = Column(Integer, default=1)
    approach = Column(String(100), nullable=True)

    code_snapshot = Column(Text, nullable=True)
    pip_requirements = Column(JSON, default=list)
    system_packages = Column(JSON, default=list)

    success = Column(Boolean, default=False)
    error_type = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    sandbox_stdout = Column(Text, nullable=True)
    sandbox_stderr = Column(Text, nullable=True)

    execution_time_ms = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    research_context = Column(JSON, nullable=True)
    failure_analysis = Column(JSON, nullable=True)

    strategy_id = Column(String(100), nullable=True)
    error_type_classified = Column(String(50), nullable=True)
    lesson_learned = Column(Text, nullable=True)
    related_attempt_ids = Column(JSON, default=list)

    skill_id = Column(String(36), ForeignKey("skills.id"), nullable=True)


class PackageMapping(Base):
    """
    Learned mappings from import names to pip packages.

    Built dynamically from successful builds and PyPI queries.
    Replaces hardcoded import_to_pip mappings.
    """
    __tablename__ = "package_mappings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    module_name = Column(String(255), nullable=False, unique=True, index=True)
    package_name = Column(String(255), nullable=False)

    confidence = Column(Float, default=0.5)
    source = Column(String(50), default="inferred")
    success_count = Column(Integer, default=0)
    failure_count = Column(Integer, default=0)

    alternatives = Column(JSON, default=list)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ResearchCache(Base):
    """
    Caches research results to avoid repeated web searches.

    Research is expensive (LLM + optional web search), so we cache:
    - Package recommendations
    - Code examples
    - Implementation approaches
    """
    __tablename__ = "research_cache"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    capability = Column(String(500), nullable=False, index=True)
    capability_hash = Column(String(64), nullable=False, unique=True)

    recommended_packages = Column(JSON, default=list)
    system_packages = Column(JSON, default=list)
    code_examples = Column(JSON, default=list)
    implementation_notes = Column(Text, nullable=True)

    sources = Column(JSON, default=list)

    is_valid = Column(Boolean, default=True)
    success_rate = Column(Float, default=0.0)
    usage_count = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)
