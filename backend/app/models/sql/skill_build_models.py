"""
SQL models for skill building and binding.

Tracks:
- SkillBinding: Links skills to agents
- SkillBuildAttempt: Records all build attempts for learning
- PackageMapping: Cached module->package mappings
- ResearchCache: Cached research results
"""
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
    capability = Column(String(500), nullable=False)  # The capability this binding provides
    binding_type = Column(String(50), default="auto")  # auto, manual, provisional
    priority = Column(Integer, default=0)  # Higher priority = preferred binding
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
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
    capability = Column(String(500), nullable=False, index=True)  # What capability was being built
    team_role = Column(String(50), nullable=True)  # researcher, architect, implementer, reviewer

    # Attempt details
    attempt_number = Column(Integer, default=1)
    approach = Column(String(100), nullable=True)  # direct, simplified, alternative, etc.

    # Code and requirements
    code_snapshot = Column(Text, nullable=True)  # Code at this attempt
    pip_requirements = Column(JSON, default=list)  # Pip packages tried
    system_packages = Column(JSON, default=list)  # Apt packages tried

    # Result
    success = Column(Boolean, default=False)
    error_type = Column(String(100), nullable=True)  # import_error, syntax_error, runtime_error, semantic_error
    error_message = Column(Text, nullable=True)
    sandbox_stdout = Column(Text, nullable=True)
    sandbox_stderr = Column(Text, nullable=True)

    # Timing
    execution_time_ms = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Context
    research_context = Column(JSON, nullable=True)  # Research data used
    failure_analysis = Column(JSON, nullable=True)  # LLM analysis of what went wrong

    # Link to final skill (if successful)
    skill_id = Column(String(36), ForeignKey("skills.id"), nullable=True)


class PackageMapping(Base):
    """
    Learned mappings from import names to pip packages.

    Built dynamically from successful builds and PyPI queries.
    Replaces hardcoded import_to_pip mappings.
    """
    __tablename__ = "package_mappings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    module_name = Column(String(255), nullable=False, unique=True, index=True)  # e.g., "cv2"
    package_name = Column(String(255), nullable=False)  # e.g., "opencv-python"

    # Confidence and source
    confidence = Column(Float, default=0.5)  # 0.0-1.0, higher = more reliable
    source = Column(String(50), default="inferred")  # hardcoded, learned, pypi, user
    success_count = Column(Integer, default=0)  # How many times this worked
    failure_count = Column(Integer, default=0)  # How many times this failed

    # Alternatives (if primary fails)
    alternatives = Column(JSON, default=list)  # ["package-alt1", "package-alt2"]

    # Metadata
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
    capability = Column(String(500), nullable=False, index=True)  # Normalized capability name
    capability_hash = Column(String(64), nullable=False, unique=True)  # For exact matching

    # Research results
    recommended_packages = Column(JSON, default=list)  # pip packages
    system_packages = Column(JSON, default=list)  # apt packages
    code_examples = Column(JSON, default=list)  # Example code snippets
    implementation_notes = Column(Text, nullable=True)  # Summary/approach

    # Sources
    sources = Column(JSON, default=list)  # URLs or references used

    # Validity
    is_valid = Column(Boolean, default=True)  # Can be invalidated if consistently failing
    success_rate = Column(Float, default=0.0)  # Success rate of builds using this cache
    usage_count = Column(Integer, default=0)  # How often this cache was used

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)  # Optional TTL
