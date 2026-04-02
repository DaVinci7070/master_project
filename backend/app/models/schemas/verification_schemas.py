"""
Verification result schemas for gap closure verification.

These models are used for deterministic verification of whether
gaps have been closed by built artifacts, without requiring LLM re-analysis.
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class GapVerificationResult(BaseModel):
    """Result of verifying a single gap's closure."""

    gap_id: str = Field(..., description="ID of the gap being verified")
    affected_capability: str = Field(..., description="The capability this gap requires")
    is_closed: bool = Field(..., description="Whether the gap is now closed")

    # What closed the gap (if closed)
    closed_by_artifact_id: Optional[str] = Field(
        None, description="ID of artifact that provides the capability"
    )
    closed_by_artifact_type: Optional[str] = Field(
        None, description="Type: 'skill', 'prompt', or 'agent'"
    )

    # Match details
    match_type: Optional[str] = Field(
        None, description="How the match was found: 'exact', 'contains', 'word_overlap', 'embedding'"
    )
    match_score: float = Field(
        default=0.0, ge=0, le=1, description="Confidence score of the match (1.0 = exact)"
    )

    # Verification metadata
    verification_method: str = Field(
        default="database_lookup",
        description="Method used: 'database_lookup' or 'embedding_similarity'"
    )


class PlanVerificationResult(BaseModel):
    """Result of verifying all gaps in a plan."""

    plan_id: str = Field(..., description="ID of the gap plan verified")
    all_closed: bool = Field(..., description="True if ALL gaps are closed")

    # Counts
    total_gaps: int = Field(..., ge=0, description="Total number of gaps in plan")
    closed_count: int = Field(..., ge=0, description="Number of gaps that are closed")
    open_count: int = Field(..., ge=0, description="Number of gaps still open")

    # Details
    open_gaps: List[dict] = Field(
        default_factory=list,
        description="List of gaps that are still open (for next cycle)"
    )
    verification_details: List[GapVerificationResult] = Field(
        default_factory=list,
        description="Verification result for each gap"
    )

    # Metadata
    verified_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="Timestamp of verification"
    )

    @property
    def closure_percentage(self) -> float:
        """Calculate percentage of closed gaps."""
        if self.total_gaps == 0:
            return 100.0
        return (self.closed_count / self.total_gaps) * 100


class CapabilityExistsResult(BaseModel):
    """Result of checking if a capability exists in the system."""

    capability_name: str = Field(..., description="The capability that was searched")
    exists: bool = Field(..., description="Whether the capability was found")

    # Provider details (if found)
    provider_id: Optional[str] = Field(None, description="ID of the provider")
    provider_type: Optional[str] = Field(
        None, description="Type: 'skill', 'prompt', or 'agent'"
    )
    provider_name: Optional[str] = Field(None, description="Name of the provider")

    # Match details
    matched_capability: Optional[str] = Field(
        None, description="The exact capability string that matched"
    )
    match_type: Optional[str] = Field(
        None, description="How matched: 'exact', 'contains', 'word_overlap'"
    )
    match_score: float = Field(default=0.0, ge=0, le=1)
