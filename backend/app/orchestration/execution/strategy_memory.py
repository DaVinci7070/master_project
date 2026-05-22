"""Speichert Team-Strategien + Reflexionen in SharedMemory für Cross-Run-Learning."""
import logging

from app.core.config import settings as default_settings
from app.models.schemas.shared_memory_schemas import FactCreate, SharedMemoryQuery

logger = logging.getLogger(__name__)

EXECUTION_REFLECTION_PROMPT = """Reflektiere über diese gescheiterte Execution.

## Challenge
{challenge_text}

## Team & Strategie
Team: {team_names}
Strategie: {strategy}
Score: {score}/1.0

## Verification-Feedback
{verification_feedback}

## Reflexions-Aufgabe
Schreibe eine KONKRETE Reflexion (3-4 Sätze) die dem Team-Planner beim nächsten ähnlichen Task hilft:
1. Was war die EIGENTLICHE Ursache des Scheiterns? (nicht nur "Score war niedrig")
2. Was hätte das Team ANDERS machen müssen?
3. Welche Team-Zusammensetzung oder Strategie wäre besser gewesen?

Schreibe als actionable Erfahrung, nicht als Post-Mortem-Bericht."""


class StrategyMemory:
    """
    Speichert erfolgreiche und gescheiterte Team-Strategien in SharedMemory.

    Ermöglicht dem TeamAssembler aus Erfahrung zu lernen:
    - Welches Team funktioniert für welchen Challenge-Typ?
    - Welche Strategien sind gescheitert und sollten vermieden werden?
    - Reflexionen aus gescheiterten Versuchen (Sprint 4: Episodic Reflection Memory)
    """

    def __init__(self, shared_memory, embedding_fn=None, llm_client=None, settings=None):
        self.shared_memory = shared_memory
        self.embedding_fn = embedding_fn
        self._llm_client = llm_client
        self._settings = settings or default_settings

    async def record_outcome(
        self,
        team_plan: "TeamPlan",
        verification_score: float,
        duration_ms: int,
        tokens_total: int,
        adapt_rounds: int = 0,
        execution_id: str = "unknown",
        project_id: str = "default",
        verification_feedback: str = "",
    ) -> None:
        """
        Speichert Execution-Outcome als SharedMemory-Fact.

        Bei Misserfolg: zusätzlich LLM-Reflexion als separater Fact.
        Bei Erfolg: verwandte Reflexionen als gelöst markieren.
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

        if success:
            await self._invalidate_resolved_reflections(
                challenge_text=team_plan.challenge_text,
                execution_id=execution_id,
            )
            return

        if self._settings.execution_reflection_enabled:
            reflection = await self._generate_execution_reflection(
                team_plan=team_plan,
                verification_score=verification_score,
                verification_feedback=verification_feedback,
            )
            if reflection:
                try:
                    embedding = None
                    if self.embedding_fn:
                        embedding = await self.embedding_fn(team_plan.challenge_text[:500])

                    await self.shared_memory.create_fact(
                        fact_data=FactCreate(
                            text=reflection,
                            confidence=0.7,
                            source_agent_id="strategy_memory_reflection",
                            execution_id=execution_id,
                            project_id=project_id,
                            tags=["execution_reflection"],
                        ),
                        embedding=embedding,
                    )
                except Exception as e:
                    logger.warning(f"Reflexion-Fact speichern fehlgeschlagen: {e}")

    async def _generate_execution_reflection(
        self,
        team_plan: "TeamPlan",
        verification_score: float,
        verification_feedback: str = "",
    ) -> str | None:
        """LLM-generierte Reflexion über eine gescheiterte Execution."""
        if not self._llm_client:
            return None

        team_names = ", ".join(a.name for a in team_plan.agents)
        prompt = EXECUTION_REFLECTION_PROMPT.format(
            challenge_text=team_plan.challenge_text[:500],
            team_names=team_names,
            strategy=team_plan.strategy or "keine angegeben",
            score=f"{verification_score:.2f}",
            verification_feedback=verification_feedback[:500],
        )

        try:
            response = await self._llm_client.chat(
                messages=[
                    {"role": "system", "content": "Du reflektierst über Agent-Executions. Kurz, konkret, zukunftsgerichtet."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=250,
            )
            return response.content.strip()
        except Exception as e:
            logger.warning(f"Execution-Reflexion fehlgeschlagen: {e}")
            return None

    async def _invalidate_resolved_reflections(
        self,
        challenge_text: str,
        execution_id: str,
    ) -> None:
        """Bei Erfolg: Verwandte Reflexionen als gelöst markieren (Confidence → 0.1)."""
        if not self.shared_memory or not self.embedding_fn:
            return

        try:
            query = SharedMemoryQuery(
                query_text=challenge_text[:200],
                max_items=5,
                score_threshold=0.5,
                tags=["execution_reflection"],
            )
            context = await self.shared_memory.retrieve_context(query)
            reflections = context.get("facts", [])

            if not reflections:
                return

            embedding = await self.embedding_fn(challenge_text[:500])

            for ref in reflections:
                ref_id = ref.get("id") if isinstance(ref, dict) else None
                ref_text = ref.get("text", "") if isinstance(ref, dict) else str(ref)
                if not ref_id:
                    continue

                await self.shared_memory.create_fact(
                    fact_data=FactCreate(
                        text=f"[GELÖST] {ref_text[:100]}... → Erfolgreich in {execution_id}",
                        confidence=0.1,
                        source_agent_id="strategy_memory_reflection",
                        execution_id=execution_id,
                        project_id=ref.get("project_id", "default") if isinstance(ref, dict) else "default",
                        tags=["execution_reflection", "resolved"],
                        supersedes_id=ref_id,
                    ),
                    embedding=embedding,
                )
        except Exception as e:
            logger.warning(f"Reflexion-Invalidierung fehlgeschlagen: {e}")

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
