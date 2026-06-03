import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.orchestration.verification.execution_verifier import ExecutionVerifier
from app.orchestration.execution.strategy_memory import StrategyMemory
from app.models.schemas.team_schemas import VerificationResult, PlannedAgent, TeamPlan


@dataclass
class FakeLLMResponse:
    content: str
    usage: dict = None

    def __post_init__(self):
        if self.usage is None:
            self.usage = {"total_tokens": 50}


def make_llm_response(data: dict) -> FakeLLMResponse:
    return FakeLLMResponse(content=json.dumps(data))


def make_settings(**overrides) -> Settings:
    """Settings mit Test-Defaults, ohne .env zu laden."""
    defaults = {
        "database_url": "sqlite+aiosqlite:///:memory:",
        "cot_verification_enabled": True,
        "self_reflection_enabled": True,
        "self_reflection_margin": 0.1,
        "execution_reflection_enabled": True,
        "reflection_memory_max_items": 3,
        "verification_completeness_threshold": 0.85,
        "adapt_threshold_new_team": 0.4,
        "adapt_threshold_escalate": 0.1,
    }
    defaults.update(overrides)
    return Settings(**defaults)


class TestCoTVerification:
    """CoT-Verification: mehrstufige Aspekt-Analyse statt Single-Shot."""

    @pytest.mark.asyncio
    async def test_cot_returns_aspect_scores(self):
        """CoT-Prompt liefert Teilaspekt-Scores und reasoning_chain."""
        llm = AsyncMock()
        llm.chat.return_value = make_llm_response({
            "aspects": [
                {"name": "Datenquelle", "status": "VORHANDEN", "evidence": "CSV geladen", "score": 0.9},
                {"name": "Verarbeitung", "status": "VORHANDEN", "evidence": "Aggregation korrekt", "score": 0.8},
                {"name": "Ausgabeformat", "status": "TEILWEISE", "evidence": "JSON statt CSV", "score": 0.5},
            ],
            "output_is_theoretical": False,
            "reasoning": "Daten korrekt verarbeitet, Ausgabeformat weicht ab.",
            "score": 0.73,
            "is_complete": False,
            "missing_aspects": ["CSV-Ausgabe"],
            "feedback_for_retry": "Ausgabe als CSV formatieren",
        })

        settings = make_settings(cot_verification_enabled=True, self_reflection_enabled=False)
        verifier = ExecutionVerifier(llm, settings=settings)

        result = await verifier.verify(
            final_output="Ergebnis: aggregierte Daten als JSON...",
            challenge_text="Aggregiere CSV-Daten und gib CSV zurück",
        )

        assert isinstance(result, VerificationResult)
        assert len(result.aspect_scores) == 3
        assert result.aspect_scores["Datenquelle"] == 0.9
        assert result.reasoning_chain == "Daten korrekt verarbeitet, Ausgabeformat weicht ab."
        assert result.score == 0.73
        assert not result.is_complete

    @pytest.mark.asyncio
    async def test_single_shot_when_cot_disabled(self):
        """Ohne CoT: kein aspect_scores, keine Self-Reflection."""
        llm = AsyncMock()
        llm.chat.return_value = make_llm_response({
            "is_complete": True,
            "score": 0.92,
            "missing_aspects": [],
            "feedback_for_retry": "",
            "output_is_theoretical": False,
        })

        settings = make_settings(cot_verification_enabled=False)
        verifier = ExecutionVerifier(llm, settings=settings)

        result = await verifier.verify(
            final_output="Alle Daten korrekt verarbeitet.",
            challenge_text="Verarbeite die Daten",
        )

        assert result.score == 0.92
        assert result.is_complete
        assert result.aspect_scores == {}
        assert not result.score_corrected
        llm.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_theoretical_output_capped(self):
        """Rein theoretischer Output → capability_gap, max Score 0.2."""
        llm = AsyncMock()
        llm.chat.return_value = make_llm_response({
            "aspects": [{"name": "Konzept", "status": "VORHANDEN", "evidence": "Beschreibung", "score": 0.15}],
            "output_is_theoretical": True,
            "reasoning": "Nur Beschreibung, keine Daten.",
            "score": 0.15,
            "is_complete": False,
            "missing_aspects": ["Echte Daten"],
            "feedback_for_retry": "Daten liefern statt beschreiben",
        })

        settings = make_settings(cot_verification_enabled=True, self_reflection_enabled=False)
        verifier = ExecutionVerifier(llm, settings=settings)

        result = await verifier.verify(
            final_output="Man könnte die Daten folgendermaßen verarbeiten...",
            challenge_text="Verarbeite die Daten",
        )

        assert result.capability_gap
        assert result.score <= 0.2

    @pytest.mark.asyncio
    async def test_capability_gap_pattern_detection(self):
        """Explizite Unfähigkeits-Signale werden sofort erkannt (kein LLM-Call)."""
        llm = AsyncMock()
        settings = make_settings()
        verifier = ExecutionVerifier(llm, settings=settings)

        result = await verifier.verify(
            final_output="Ich habe keinen Zugriff auf die Datenbank.",
            challenge_text="Lese die Tabelle aus",
        )

        assert result.capability_gap
        assert result.score == 0.0
        assert len(result.gap_indicators) > 0
        llm.chat.assert_not_called()


class TestSelfReflection:
    """Self-Reflection: Score-Korrektur bei Grenzfällen."""

    @pytest.mark.asyncio
    async def test_reflection_corrects_score_near_threshold(self):
        """Score nahe Threshold (0.85 ± 0.1) → Self-Reflection kann korrigieren."""
        call_count = 0

        async def mock_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return make_llm_response({
                    "aspects": [
                        {"name": "A", "status": "VORHANDEN", "evidence": "ok", "score": 0.9},
                        {"name": "B", "status": "VORHANDEN", "evidence": "ok", "score": 0.85},
                    ],
                    "output_is_theoretical": False,
                    "reasoning": "Gut aber knapp.",
                    "score": 0.82,
                    "is_complete": False,
                    "missing_aspects": [],
                    "feedback_for_retry": "",
                })
            return make_llm_response({
                "reflection": "Aspekt-Scores (0.9, 0.85) rechtfertigen höheren Gesamt-Score.",
                "score_adjustment_needed": True,
                "corrected_score": 0.87,
                "correction_reason": "Inkonsistenz zwischen Aspekt- und Gesamt-Score.",
            })

        llm = AsyncMock()
        llm.chat.side_effect = mock_chat

        settings = make_settings(
            cot_verification_enabled=True,
            self_reflection_enabled=True,
            self_reflection_margin=0.1,
        )
        verifier = ExecutionVerifier(llm, settings=settings)

        result = await verifier.verify(
            final_output="Korrekte Ergebnisse mit allen Daten.",
            challenge_text="Verarbeite Daten",
        )

        assert result.score_corrected
        assert result.original_score == 0.82
        assert result.score == 0.87
        assert result.is_complete
        assert result.self_reflection != ""
        assert llm.chat.call_count == 2

    @pytest.mark.asyncio
    async def test_no_reflection_when_score_far_from_threshold(self):
        """Score weit von Threshold → keine Self-Reflection (Token-Sparend)."""
        llm = AsyncMock()
        llm.chat.return_value = make_llm_response({
            "aspects": [{"name": "A", "status": "VORHANDEN", "evidence": "ok", "score": 0.2}],
            "output_is_theoretical": False,
            "reasoning": "Klar unvollständig.",
            "score": 0.2,
            "is_complete": False,
            "missing_aspects": ["Alles"],
            "feedback_for_retry": "Komplett neu machen",
        })

        settings = make_settings(
            cot_verification_enabled=True,
            self_reflection_enabled=True,
            self_reflection_margin=0.1,
        )
        verifier = ExecutionVerifier(llm, settings=settings)

        result = await verifier.verify(
            final_output="Minimal-Ergebnis",
            challenge_text="Aufgabe XY",
        )

        assert not result.score_corrected
        assert result.original_score is None
        llm.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_reflection_disabled_skips_second_call(self):
        """Self-Reflection disabled → nur ein LLM-Call auch bei Grenzfall."""
        llm = AsyncMock()
        llm.chat.return_value = make_llm_response({
            "aspects": [{"name": "A", "status": "VORHANDEN", "evidence": "ok", "score": 0.84}],
            "output_is_theoretical": False,
            "reasoning": "Grenzfall.",
            "score": 0.84,
            "is_complete": False,
            "missing_aspects": [],
            "feedback_for_retry": "",
        })

        settings = make_settings(
            cot_verification_enabled=True,
            self_reflection_enabled=False,
        )
        verifier = ExecutionVerifier(llm, settings=settings)

        result = await verifier.verify(
            final_output="Fast vollständig",
            challenge_text="Aufgabe",
        )

        assert result.score == 0.84
        assert not result.score_corrected
        llm.chat.assert_called_once()


class TestEpisodicReflectionMemory:
    """Episodic Memory: Reflexionen nach Misserfolg speichern, bei Erfolg invalidieren."""

    def _make_team_plan(self) -> TeamPlan:
        return TeamPlan(
            challenge_text="Erstelle einen Baustellenbericht aus Audio",
            agents=[
                PlannedAgent(agent_id="a1", name="Transkriptor", role="Transkription"),
                PlannedAgent(agent_id="a2", name="Berichtsschreiber", role="Report"),
            ],
            execution_waves=[["a1"], ["a2"]],
            rationale="Audio → Text → Bericht Pipeline",
            strategy="sequential_pipeline",
        )

    @pytest.mark.asyncio
    async def test_failure_generates_reflection(self):
        """Gescheiterte Execution → LLM-Reflexion + SharedMemory-Fact."""
        shared_memory = AsyncMock()
        shared_memory.create_fact = AsyncMock()
        embedding_fn = AsyncMock(return_value=[0.1] * 128)

        llm = AsyncMock()
        llm.chat.return_value = FakeLLMResponse(
            content="Der Transkriptor hat keine Audio-Datei erhalten. "
                    "Nächstes Mal muss der Datei-Pfad als Artifact weitergereicht werden."
        )

        settings = make_settings(execution_reflection_enabled=True)
        memory = StrategyMemory(shared_memory, embedding_fn, llm, settings=settings)

        await memory.record_outcome(
            team_plan=self._make_team_plan(),
            verification_score=0.3,
            duration_ms=5000,
            tokens_total=200,
            adapt_rounds=2,
            verification_feedback="Kein Transkript vorhanden",
        )

        assert shared_memory.create_fact.call_count == 2
        calls = shared_memory.create_fact.call_args_list
        tags_list = [c.kwargs["fact_data"].tags for c in calls]
        assert ["team_plan", "execution_outcome"] in tags_list
        assert ["execution_reflection"] in tags_list
        llm.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_success_invalidates_reflections(self):
        """Erfolgreiche Execution → alte Reflexionen als gelöst markieren."""
        shared_memory = AsyncMock()
        shared_memory.create_fact = AsyncMock()
        shared_memory.retrieve_context = AsyncMock(return_value={
            "facts": [
                {"id": "ref-1", "text": "Alte Reflexion: Audio fehlte", "project_id": "default"},
            ]
        })
        embedding_fn = AsyncMock(return_value=[0.1] * 128)

        settings = make_settings(execution_reflection_enabled=True)
        memory = StrategyMemory(shared_memory, embedding_fn, settings=settings)

        await memory.record_outcome(
            team_plan=self._make_team_plan(),
            verification_score=0.92,
            duration_ms=3000,
            tokens_total=150,
        )

        calls = shared_memory.create_fact.call_args_list
        assert any(
            "GELÖST" in c.kwargs["fact_data"].text
            and c.kwargs["fact_data"].confidence == 0.1
            for c in calls
        )

    @pytest.mark.asyncio
    async def test_no_reflection_when_disabled(self):
        """execution_reflection_enabled=False → kein LLM-Call, nur Outcome-Fact."""
        shared_memory = AsyncMock()
        shared_memory.create_fact = AsyncMock()
        llm = AsyncMock()

        settings = make_settings(execution_reflection_enabled=False)
        memory = StrategyMemory(shared_memory, llm_client=llm, settings=settings)

        await memory.record_outcome(
            team_plan=self._make_team_plan(),
            verification_score=0.3,
            duration_ms=5000,
            tokens_total=200,
        )

        assert shared_memory.create_fact.call_count == 1
        llm.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_shared_memory_graceful(self):
        """Ohne SharedMemory → kein Fehler."""
        settings = make_settings()
        memory = StrategyMemory(shared_memory=None, settings=settings)

        await memory.record_outcome(
            team_plan=self._make_team_plan(),
            verification_score=0.5,
            duration_ms=1000,
            tokens_total=100,
        )
