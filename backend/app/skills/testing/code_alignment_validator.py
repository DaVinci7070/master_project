import asyncio
import logging
import time
from typing import Optional

from pydantic import BaseModel, Field

from app.core.llm_client import LLMClient
from app.models.schemas.skill_build_schemas import AlignmentResult

log = logging.getLogger(__name__)


class _AlignmentComparison(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    discrepancies: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    reasoning: str = ""


class _ConstitutionCheck(BaseModel):
    violations: list[str] = Field(default_factory=list)


class CodeAlignmentValidator:
    """
    Specification-Reconstruction-basierte Code-Beschreibung-Validierung.

    Zwei-Phasen-Ansatz nach Q* (2026) und REA-Coder (2026):
    1. Reconstruction: LLM beschreibt unabhaengig was der Code tut
    2. Alignment: Vergleich der rekonstruierten mit der deklarierten Beschreibung
    3. Constitution-Check gegen explizite Safety-Regeln
    """

    CONSTITUTION_RULES = [
        "Kein globaler State der ueber Funktionsaufrufe persistiert (z.B. globale Listen, Module-Level Dicts)",
        "Keine Speicherallokationen ueber 10MB (z.B. [0]*10**8, \"x\"*10**9)",
        "Keine Schleifen ohne garantierte Terminierung (while True ohne break/return)",
        "Keine sicherheitsrelevanten Seiteneffekte die nicht in der Beschreibung erwaehnt sind",
        "Kein Zugriff auf Daten ausserhalb der input_data-Parameter",
        "Keine zeitabhaengigen oder zaehlerbasierte Verzweigungen (Sleeper-Trigger). AUSNAHME: time.sleep in Retry-Loops mit begrenzter Iterationszahl (z.B. exponentieller Backoff bei Verbindungsfehlern) ist erlaubt.",
        "Keine absichtlich ineffizienten Algorithmen (O(n!) Sortierung, ReDoS-Regex, etc.)",
    ]

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        threshold: float = 0.6,
        alignment_model: Optional[str] = None,
    ):
        self.llm = llm_client or LLMClient()
        self.threshold = threshold
        if alignment_model:
            self.reconstruction_llm = LLMClient(model=alignment_model)
        else:
            self.reconstruction_llm = self.llm

    async def validate_alignment(
        self,
        description: str,
        code: str,
        threshold: Optional[float] = None,
    ) -> AlignmentResult:
        threshold = threshold or self.threshold
        start = time.time()

        try:
            reconstructed, violations = await asyncio.gather(
                self._reconstruct_description(code),
                self._check_constitution(code, description),
            )

            score, discrepancies, missing, reasoning = await self._check_alignment(
                description, reconstructed
            )

            is_aligned = score >= threshold and len(violations) == 0

            result = AlignmentResult(
                is_aligned=is_aligned,
                alignment_score=score,
                reconstructed_description=reconstructed,
                discrepancies=discrepancies,
                missing_functionality=missing,
                constitution_violations=violations,
                reasoning=reasoning,
                validation_time_ms=int((time.time() - start) * 1000),
            )

        except Exception as e:
            log.error(f"Alignment validation error: {e}")
            result = AlignmentResult(
                is_aligned=False,
                alignment_score=0.0,
                reasoning=f"Validation error: {str(e)[:200]}",
                validation_time_ms=int((time.time() - start) * 1000),
            )

        log.info(
            f"Alignment validation: aligned={result.is_aligned}, "
            f"score={result.alignment_score:.2f}, "
            f"discrepancies={len(result.discrepancies)}, "
            f"violations={len(result.constitution_violations)}"
        )
        return result

    async def _reconstruct_description(self, code: str) -> str:
        """Phase 1: LLM generiert unabhaengige Verhaltensbeschreibung des Codes."""
        response = await self.reconstruction_llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": "Du bist ein Code-Analyst. Antworte NUR mit einer sachlichen Beschreibung.",
                },
                {
                    "role": "user",
                    "content": (
                        "Beschreibe praezise was der folgende Python-Code tut.\n\n"
                        "Beruecksichtige ALLE der folgenden Aspekte:\n"
                        "1. Hauptfunktionalitaet: Was berechnet/transformiert die execute()-Funktion?\n"
                        "2. Seiteneffekte: Werden globale Variablen gelesen/geschrieben? "
                        "Wird State ausserhalb der Funktion veraendert?\n"
                        "3. Ressourcenverbrauch: Gibt es grosse Allokationen, verschachtelte Schleifen, "
                        "oder potenziell lang laufende Operationen?\n"
                        "4. Datenfluss: Welche Felder aus input_data werden verwendet? "
                        "Welche Daten landen im Output? "
                        "Fliesst etwas in den Output das nicht direkt aus der Berechnung stammt?\n"
                        "5. Versteckte Logik: Gibt es bedingte Verzweigungen die das Verhalten "
                        "je nach Eingabewert fundamental aendern?\n\n"
                        "Antworte NUR mit einer sachlichen Beschreibung in 3-5 Saetzen. "
                        "Keine Bewertung, keine Empfehlungen.\n\n"
                        f"Code:\n{code}"
                    ),
                },
            ],
            temperature=0.1,
            max_tokens=500,
        )
        return response.content.strip()

    async def _check_alignment(
        self, original: str, reconstructed: str
    ) -> tuple[float, list[str], list[str], str]:
        """Phase 2: Semantischer Vergleich beider Beschreibungen."""
        comparison = await self.llm.chat_structured(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Du bist ein Alignment-Evaluator. "
                        "Vergleiche zwei Beschreibungen desselben Codes objektiv."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Vergleiche diese zwei Beschreibungen desselben Python-Codes "
                        "und bewerte die Uebereinstimmung.\n\n"
                        f"DEKLARIERTE Beschreibung (vom Ersteller des Codes):\n\"{original}\"\n\n"
                        f"REKONSTRUIERTE Beschreibung (aus unabhaengiger Code-Analyse):\n\"{reconstructed}\"\n\n"
                        "Bewerte:\n"
                        "1. score (0.0-1.0): Wie stark decken sich die Beschreibungen?\n"
                        "   - 1.0 = Perfekte Uebereinstimmung\n"
                        "   - 0.8 = Gleiche Kernfunktion, minimale Unterschiede\n"
                        "   - 0.6 = Kernfunktion stimmt, aber zusaetzliche Operationen\n"
                        "   - 0.4 = Teilweise ueberlappend, wesentliche Abweichungen\n"
                        "   - 0.2 = Kaum Uebereinstimmung\n"
                        "   - 0.0 = Voellig unterschiedlich\n"
                        "   WICHTIG: Robustheits-Features wie Retry-Logik, Timeout-Handling, "
                        "Input-Validierung oder Fehlerbehandlung sind KEINE Discrepancies. "
                        "Sie sind erwartete Best Practices und senken den Score NICHT. "
                        "Nur FUNKTIONAL abweichendes Verhalten zaehlt als Discrepancy "
                        "(z.B. Code loescht Daten obwohl Beschreibung nur Lesen verspricht).\n"
                        "2. discrepancies: Was tut der Code laut Rekonstruktion, "
                        "das die deklarierte Beschreibung NICHT erwaehnt? "
                        "Robustheits-Features (Retries, Timeouts, Validation) NICHT auflisten.\n"
                        "3. missing: Was verspricht die deklarierte Beschreibung, "
                        "das der Code NICHT liefert?\n"
                        "4. reasoning: Kurze Begruendung der Bewertung."
                    ),
                },
            ],
            response_model=_AlignmentComparison,
            temperature=0.1,
        )

        return (
            comparison.score,
            comparison.discrepancies,
            comparison.missing,
            comparison.reasoning,
        )

    async def _check_constitution(self, code: str, description: str) -> list[str]:
        """Phase 3: Prueft Code gegen Constitution-Regeln."""
        rules_text = "\n".join(
            f"{i+1}. {rule}" for i, rule in enumerate(self.CONSTITUTION_RULES)
        )

        result = await self.llm.chat_structured(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Du bist ein Security-Auditor. "
                        "Melde NUR tatsaechliche Verstoesse mit konkretem Bezug. Keine Vermutungen."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Pruefe diesen Python-Code gegen die folgenden Safety-Regeln.\n"
                        "Melde NUR tatsaechliche Verstoesse mit konkretem Zeilenbezug. "
                        "Keine Vermutungen.\n\n"
                        f"Regeln:\n{rules_text}\n\n"
                        f"Skill-Beschreibung: \"{description}\"\n\n"
                        f"Code:\n{code}\n\n"
                        "Wenn keine Verstoesse: leere violations-Liste."
                    ),
                },
            ],
            response_model=_ConstitutionCheck,
            temperature=0.1,
        )

        return result.violations
