from typing import Optional

from pydantic import BaseModel, Field


class EvolutionReport(BaseModel):
    """Summary of a single evolution loop run for an execution."""

    execution_id: str = Field(
        ...,
        description="UUID of the execution this evolution ran against.",
    )
    attempted: int = Field(
        default=0,
        ge=0,
        description="Number of improvements attempted (Control Agent approved).",
    )
    succeeded: int = Field(
        default=0,
        ge=0,
        description="Number of improvements that produced an A/B test.",
    )
    skipped_by_strike: int = Field(
        default=0,
        ge=0,
        description="Findings rejected due to 3-strike rule.",
    )
    reason: Optional[str] = Field(
        default=None,
        description="Optional reason when attempted/succeeded are zero.",
    )