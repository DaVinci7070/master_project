from enum import Enum

from pydantic import BaseModel, Field


class AdaptAction(str, Enum):
    """Eskalationsstufe nach Verification."""
    PASS = "pass"
    REPLAN_FEEDBACK = "replan_feedback"
    REPLAN_NEW_TEAM = "replan_new_team"
    ESCALATE = "escalate"


class PlannedAgent(BaseModel):
    """Ein Agent im Team-Plan — muss in DB existieren."""
    agent_id: str
    name: str
    role: str
    dependencies: list[str] = []
    produces_artifacts: list[str] = []
    consumes_artifacts: list[str] = []


class MissingCapability(BaseModel):
    """Eine Fähigkeit die im Pool fehlt und gebaut werden muss."""
    capability: str
    description: str
    rationale: str
    suggested_approach: str = ""


class TeamPlan(BaseModel):
    """Aufgabenspezifischer Team-Plan mit existierenden Agents."""
    team_id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    challenge_text: str
    agents: list[PlannedAgent]
    execution_waves: list[list[str]] = []
    rationale: str
    strategy: str = ""


class GapReport(BaseModel):
    """Bericht über fehlende Capabilities — geht ans Developer Team."""
    challenge_text: str
    missing_capabilities: list[MissingCapability]
    available_but_insufficient: list[str] = []
    planner_rationale: str


class PlanValidation(BaseModel):
    """Ergebnis der Plan-Validierung."""
    valid: bool
    issues: list[str] = []


class VerificationResult(BaseModel):
    """Ergebnis der Execution-Verification."""
    is_complete: bool
    score: float = 0.0
    missing_aspects: list[str] = []
    feedback_for_retry: str = ""
    capability_gap: bool = False
    gap_indicators: list[str] = []
    aspect_scores: dict[str, float] = {}
    reasoning_chain: str = ""
    self_reflection: str = ""
    score_corrected: bool = False
    original_score: float | None = None


class AdaptDecision(BaseModel):
    """Entscheidung des Adapt-Loops: Was tun nach Verification?"""
    action: AdaptAction
    feedback_artifact: dict | None = None
    gaps_to_build: list[str] | None = None
    replan_context: str = ""
