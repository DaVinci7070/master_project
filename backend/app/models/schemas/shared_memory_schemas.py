from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class FactBase(BaseModel):
    """Base fields for a Fact (observation with confidence score)."""
    text: str = Field(..., min_length=1, description="The observation content")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score from 0.0 to 1.0"
    )
    source_agent_id: str = Field(..., min_length=1, description="Agent that created this fact")
    execution_id: str = Field(..., min_length=1, description="Execution run identifier")
    project_id: str = Field(..., min_length=1, description="Project identifier")
    tags: list[str] = Field(default_factory=list, description="Tags for filtering")
    supersedes_id: Optional[str] = Field(
        None,
        max_length=36,
        description="ID of previous fact this supersedes (for versioning)"
    )
    embedding_id: Optional[str] = Field(
        None,
        max_length=255,
        description="Qdrant point ID, set after embedding"
    )


class FactCreate(FactBase):
    """Schema for creating a new fact."""
    pass


class FactResponse(FactBase):
    """Schema for fact response."""
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Unique identifier")
    created_at: datetime = Field(..., description="Creation timestamp")


class HypothesisBase(BaseModel):
    """Base fields for a Hypothesis (system learning)."""
    text: str = Field(..., min_length=1, description="The hypothesis statement")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score from 0.0 to 1.0"
    )
    source_agent_id: str = Field(..., min_length=1, description="Agent that created this hypothesis")
    execution_id: str = Field(..., min_length=1, description="Execution run identifier")
    project_id: str = Field(..., min_length=1, description="Project identifier")
    status: Literal["active", "confirmed", "contradicted"] = Field(
        default="active",
        description="Hypothesis status"
    )
    supporting_fact_ids: list[str] = Field(
        default_factory=list,
        description="IDs of facts that support this hypothesis"
    )
    contradicting_fact_ids: list[str] = Field(
        default_factory=list,
        description="IDs of facts that contradict this hypothesis"
    )


class HypothesisCreate(HypothesisBase):
    """Schema for creating a new hypothesis."""
    pass


class HypothesisResponse(HypothesisBase):
    """Schema for hypothesis response."""
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Unique identifier")
    created_at: datetime = Field(..., description="Creation timestamp")


class RelationBase(BaseModel):
    """Base fields for a Relation (causal chain between facts)."""
    relation_type: Literal["causes", "caused_by"] = Field(
        ...,
        description="Causal relation type"
    )
    source_fact_id: str = Field(..., min_length=1, description="The cause fact ID")
    target_fact_id: str = Field(..., min_length=1, description="The effect fact ID")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score from 0.0 to 1.0"
    )
    source_agent_id: str = Field(..., min_length=1, description="Agent that created this relation")
    execution_id: str = Field(..., min_length=1, description="Execution run identifier")
    project_id: str = Field(..., min_length=1, description="Project identifier")


class RelationCreate(RelationBase):
    """Schema for creating a new relation."""
    pass


class RelationResponse(RelationBase):
    """Schema for relation response."""
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Unique identifier")
    created_at: datetime = Field(..., description="Creation timestamp")


class SharedMemoryQuery(BaseModel):
    """Schema for querying shared memory with filters."""
    query_text: str = Field(..., min_length=1, description="Semantic search query")
    agent_id: Optional[str] = Field(None, description="Filter by source agent")
    project_id: Optional[str] = Field(None, description="Filter by project")
    cross_project: bool = Field(default=False, description="Search across all projects")
    exclude_project_id: Optional[str] = Field(
        None,
        description="Exclude results from this project (for cross-project)"
    )
    min_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold"
    )
    max_items: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum items to return (soft limit)"
    )
    score_threshold: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Mindest-Cosine-Similarity für Treffer (semantisch, nicht confidence). "
            "Memory-Redesign Sprint A — G-Memory-inspirierter Filter."
        ),
    )
    include_hypotheses: bool = Field(default=True, description="Include hypotheses in results")
    include_relations: bool = Field(default=True, description="Include relations in results")
    tags: Optional[list[str]] = Field(None, description="Filter by tags")
