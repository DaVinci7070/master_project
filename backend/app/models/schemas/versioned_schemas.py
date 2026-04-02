"""
Pydantic schemas for versioned models (Prompt, Agent, Skill).

Uses Pydantic v2 with ConfigDict for SQLAlchemy model integration.
"""
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# Prompt Schemas
# ============================================================================

class PromptCreate(BaseModel):
    """Schema for creating a new prompt."""
    name: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    parent_id: Optional[str] = Field(None, max_length=36)
    prompt_metadata: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class PromptUpdate(BaseModel):
    """Schema for updating an existing prompt."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    content: Optional[str] = Field(None, min_length=1)
    prompt_metadata: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None


class PromptResponse(BaseModel):
    """Schema for prompt response."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    parent_id: Optional[str] = None
    name: str
    content: str
    prompt_metadata: dict[str, Any]
    is_active: bool
    created_at: datetime


# ============================================================================
# Agent Schemas
# ============================================================================

class AgentCreate(BaseModel):
    """Schema for creating a new agent."""
    name: str = Field(..., min_length=1, max_length=255)
    io_schema: dict[str, Any] = Field(..., description="Input/output schema for the agent")
    capabilities: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    prompt_id: Optional[str] = Field(None, max_length=36)
    is_active: bool = True


class AgentUpdate(BaseModel):
    """Schema for updating an existing agent."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    io_schema: Optional[dict[str, Any]] = None
    capabilities: Optional[list[str]] = None
    dependencies: Optional[list[str]] = None
    prompt_id: Optional[str] = Field(None, max_length=36)
    is_active: Optional[bool] = None


class AgentResponse(BaseModel):
    """Schema for agent response."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    capabilities: list[str]
    dependencies: list[str]
    io_schema: dict[str, Any]
    is_active: bool
    prompt_id: Optional[str] = None
    created_at: datetime


# ============================================================================
# Skill Schemas
# ============================================================================

class SkillTestCase(BaseModel):
    """Schema for a skill test case."""
    name: str = Field(..., min_length=1, max_length=255)
    input: dict[str, Any] = Field(default_factory=dict)
    expected_output: Any = None
    description: Optional[str] = None


class SkillCreate(BaseModel):
    """Schema for creating a new skill."""
    name: str = Field(..., min_length=1, max_length=255)
    code: str = Field(..., min_length=1)
    parent_id: Optional[str] = Field(None, max_length=36)
    description: Optional[str] = None
    test_cases: list[SkillTestCase] = Field(default_factory=list)
    skill_metadata: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class SkillUpdate(BaseModel):
    """Schema for updating an existing skill."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    code: Optional[str] = Field(None, min_length=1)
    description: Optional[str] = None
    test_cases: Optional[list[SkillTestCase]] = None
    skill_metadata: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None


class SkillResponse(BaseModel):
    """Schema for skill response."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    parent_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    code: str
    test_cases: list[dict[str, Any]]
    skill_metadata: dict[str, Any]
    is_active: bool
    created_at: datetime
