"""Generic Artifact model for session-scoped data passing."""
from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator


class Artifact(BaseModel):
    """
    Generic artifact envelope for inter-agent communication.

    Minimal fields per CONTEXT decision:
    - artifact_type: Identifies the artifact kind
    - payload: The actual data (dict)
    - source_agent_id: Which agent produced this
    - timestamp: When it was created

    Session-only: Discarded after execution run.
    """
    artifact_type: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Type identifier for artifact discovery"
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Artifact data (schema validated at write time)"
    )
    source_agent_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Agent that produced this artifact"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp"
    )

    # Optional metadata
    execution_id: Optional[str] = Field(
        default=None,
        description="Execution run this artifact belongs to"
    )
    correlation_id: Optional[str] = Field(
        default=None,
        description="For tracing related artifacts"
    )

    @field_validator("artifact_type")
    @classmethod
    def validate_artifact_type(cls, v: str) -> str:
        """Ensure artifact_type is snake_case identifier."""
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("artifact_type must be alphanumeric with underscores/hyphens")
        return v.lower()

    model_config = {"frozen": True}  # Immutable once created


class ArtifactDeclaration(BaseModel):
    """
    Declaration of artifact types an agent consumes or produces.
    Used for pre-validation and discovery (per CONTEXT).
    """
    artifact_type: str = Field(..., description="Type identifier")
    direction: str = Field(..., pattern="^(consumes|produces)$")
    payload_schema: Optional[dict[str, Any]] = Field(
        default=None,
        description="JSON Schema for payload validation"
    )
    required: bool = Field(
        default=True,
        description="Whether this artifact is required (consumes) or always produced (produces)"
    )


class AgentArtifactContract(BaseModel):
    """
    Contract declaring what artifacts an agent consumes and produces.
    Enables pre-validation before execution.
    """
    agent_id: str
    declarations: list[ArtifactDeclaration] = Field(default_factory=list)

    def consumes(self) -> list[str]:
        """Get list of artifact types this agent consumes."""
        return [d.artifact_type for d in self.declarations if d.direction == "consumes"]

    def produces(self) -> list[str]:
        """Get list of artifact types this agent produces."""
        return [d.artifact_type for d in self.declarations if d.direction == "produces"]

    def get_schema(self, artifact_type: str) -> Optional[dict[str, Any]]:
        """Get schema for a specific artifact type."""
        for d in self.declarations:
            if d.artifact_type == artifact_type:
                return d.payload_schema
        return None
