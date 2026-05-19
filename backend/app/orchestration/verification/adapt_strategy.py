"""3-Stufen-Eskalationslogik nach Execution-Verification."""
import logging

from app.models.schemas.team_schemas import (
    AdaptAction,
    AdaptDecision,
    VerificationResult,
)

logger = logging.getLogger(__name__)


class AdaptStrategy:
    """
    Entscheidet WIE auf ein Verification-Ergebnis reagiert wird.

    Drei Eskalationsstufen statt blindem Retry:
    - REPLAN_FEEDBACK: Output war auf dem richtigen Weg, braucht Nachbesserung
    - REPLAN_NEW_TEAM: Ansatz war falsch, neues Team/andere Strategie nötig
    - ESCALATE: Capability fehlt komplett, Gap-Building nötig
    """

    def __init__(self, settings):
        self.settings = settings

    def determine_action(
        self,
        verification: VerificationResult,
        replan_round: int,
    ) -> AdaptDecision:
        """
        Score-basierte Eskalation mit Capability-Gap-Erkennung.

        Score ≥ 0.85           → PASS (nicht aufgerufen, im Loop abgefangen)
        Score 0.4–0.85         → REPLAN_FEEDBACK (gleiche Agents, Feedback)
        Score 0.1–0.4          → REPLAN_NEW_TEAM (neuer Plan, andere Strategie)
        Score < 0.1 oder Gap   → ESCALATE (Gap-Building)

        Bei zweitem Fehlversuch mit REPLAN_FEEDBACK: Eskalation zu REPLAN_NEW_TEAM.
        """
        if verification.capability_gap:
            return AdaptDecision(
                action=AdaptAction.ESCALATE,
                gaps_to_build=verification.gap_indicators,
                replan_context=(
                    f"Capability-Gap erkannt: {', '.join(verification.gap_indicators)}. "
                    f"Fehlende Fähigkeiten müssen zuerst gebaut werden."
                ),
            )

        score = verification.score
        threshold_new_team = self.settings.adapt_threshold_new_team
        threshold_escalate = self.settings.adapt_threshold_escalate

        if score < threshold_escalate:
            return AdaptDecision(
                action=AdaptAction.ESCALATE,
                gaps_to_build=verification.missing_aspects,
                replan_context=f"Score {score:.2f} — grundlegende Fähigkeiten fehlen.",
            )

        if score < threshold_new_team:
            return AdaptDecision(
                action=AdaptAction.REPLAN_NEW_TEAM,
                replan_context=(
                    f"Score {score:.2f} — Ansatz war grundlegend falsch. "
                    f"Fehlende Aspekte: {', '.join(verification.missing_aspects)}. "
                    f"Feedback: {verification.feedback_for_retry}"
                ),
            )

        # Score 0.4–0.85: Feedback-Retry, aber nach 2. Fehlversuch eskalieren
        if replan_round >= 1:
            return AdaptDecision(
                action=AdaptAction.REPLAN_NEW_TEAM,
                replan_context=(
                    f"Feedback-Retry hat nach {replan_round + 1} Runden nicht gereicht "
                    f"(Score {score:.2f}). Anderer Ansatz nötig. "
                    f"Fehlend: {', '.join(verification.missing_aspects)}"
                ),
            )

        return AdaptDecision(
            action=AdaptAction.REPLAN_FEEDBACK,
            feedback_artifact={
                "artifact_type": "verification_feedback",
                "payload": {
                    "is_complete": verification.is_complete,
                    "score": verification.score,
                    "missing_aspects": verification.missing_aspects,
                    "feedback": verification.feedback_for_retry,
                },
            },
        )
