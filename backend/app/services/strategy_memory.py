"""Speichert Team-Strategien in SharedMemory für Cross-Run-Learning."""
import logging

from app.models.schemas.shared_memory_schemas import FactCreate

logger = logging.getLogger(__name__)


class StrategyMemory:
    """
    Speichert erfolgreiche und gescheiterte Team-Strategien in SharedMemory.

    Ermöglicht dem TeamAssembler aus Erfahrung zu lernen:
    - Welches Team funktioniert für welchen Challenge-Typ?
    - Welche Strategien sind gescheitert und sollten vermieden werden?
    """

    def __init__(self, shared_memory, embedding_fn=None):
        self.shared_memory = shared_memory
        self.embedding_fn = embedding_fn

    async def record_outcome(
        self,
        team_plan: "TeamPlan",
        verification_score: float,
        duration_ms: int,
        tokens_total: int,
        adapt_rounds: int = 0,
        execution_id: str = "unknown",
        project_id: str = "default",
    ) -> None:
        """
        Speichert Execution-Outcome als SharedMemory-Fact.

        Sowohl Erfolge als auch Misserfolge werden gespeichert —
        Misserfolge helfen dem Planner alternative Strategien zu wählen.
        """
        if not self.shared_memory:
            return

        team_names = [a.name for a in team_plan.agents]
        success = verification_score >= 0.85

        content = (
            f"Challenge-Typ: {self._extract_challenge_type(team_plan.challenge_text)}. "
            f"Strategie: {team_plan.strategy or 'keine angegeben'}. "
            f"Team: {', '.join(team_names)}. "
            f"Score: {verification_score:.2f}. "
            f"{'ERFOLGREICH' if success else 'GESCHEITERT'}. "
            f"Adapt-Runden: {adapt_rounds}. "
            f"Dauer: {duration_ms}ms, Tokens: {tokens_total}."
        )

        if not success:
            content += (
                f" Empfehlung: Andere Strategie als '{team_plan.strategy}' "
                f"für diesen Challenge-Typ wählen."
            )

        try:
            embedding = None
            if self.embedding_fn:
                embedding = await self.embedding_fn(team_plan.challenge_text[:500])

            await self.shared_memory.create_fact(
                fact_data=FactCreate(
                    text=content,
                    confidence=verification_score,
                    source_agent_id="team_assembler",
                    execution_id=execution_id,
                    project_id=project_id,
                    tags=["team_plan", "execution_outcome"],
                ),
                embedding=embedding,
            )
        except Exception as e:
            logger.warning(f"Strategy-Memory speichern fehlgeschlagen: {e}")

    @staticmethod
    def _extract_challenge_type(challenge_text: str) -> str:
        """Extrahiert einen groben Challenge-Typ aus dem Text."""
        text_lower = challenge_text.lower()
        if any(kw in text_lower for kw in ["sql", "datenbank", "tabelle", "query"]):
            return "database"
        if any(kw in text_lower for kw in ["csv", "etl", "import", "parse"]):
            return "data_processing"
        if any(kw in text_lower for kw in ["audio", "transkri", "aufnahme"]):
            return "audio_transcription"
        if any(kw in text_lower for kw in ["bericht", "report", "zusammenfassung"]):
            return "report_generation"
        return "general"
