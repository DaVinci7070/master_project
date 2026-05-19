"""Prüft ob Execution-Ergebnisse die Challenge vollständig beantworten."""
import json
import logging
import re

from app.models.schemas.team_schemas import VerificationResult

logger = logging.getLogger(__name__)

CAPABILITY_GAP_PATTERNS = [
    "ich habe keinen zugriff",
    "ich kann keine sql",
    "kann keine datenbankverbindung",
    "keinen direkten zugriff auf",
    "muss in einer lokalen entwicklungsumgebung",
    "kann diese anfrage nicht bearbeiten",
    "habe keinen zugang zu",
    "nicht in der lage",
    "dieser prozess muss extern",
    "i cannot fulfill",
    "i don't have access",
]


class ExecutionVerifier:
    """
    Prüft ob Execution-Ergebnisse die Challenge vollständig beantworten.
    Erkennt den Unterschied zwischen "unvollständig" und "grundsätzlich unfähig".
    """

    def __init__(self, llm_client):
        self.llm = llm_client

    async def verify(
        self,
        final_output: str,
        challenge_text: str,
    ) -> VerificationResult:
        """
        Prüft Vollständigkeit und erkennt Capability-Gaps.

        Zwei Prüfungen:
        1. Pattern-Match: Erkennt explizite Unfähigkeits-Signale im Output
        2. LLM-Bewertung: Prüft inhaltliche Vollständigkeit
        """
        gap_indicators = self._detect_capability_gaps(final_output)
        if gap_indicators:
            return VerificationResult(
                is_complete=False,
                score=0.0,
                missing_aspects=["Agent hat zugegeben die Aufgabe nicht ausführen zu können"],
                feedback_for_retry="",
                capability_gap=True,
                gap_indicators=gap_indicators,
            )

        prompt = f"""Prüfe ob dieser Output die Aufgabe vollständig beantwortet.

## Aufgabe
{challenge_text}

## Output
{final_output[:4000]}

## Bewertung
Prüfe kritisch:
1. Enthält der Output KONKRETE Daten (Zahlen, Namen, Datumsangaben) oder nur BESCHREIBUNGEN wie man sie bekommen könnte?
2. Hat der Agent die Aufgabe tatsächlich AUSGEFÜHRT oder nur den Prozess BESCHRIEBEN?
3. Gibt es Abschnitte die vage bleiben statt mit echten Ergebnissen belegt zu sein?
4. Welche Aspekte der Aufgabe fehlen komplett?

WICHTIG: Ein Output der nur beschreibt WAS MAN TUN MÜSSTE (Vorschläge, Schemas, Prozessbeschreibungen)
ohne tatsächliche Ergebnisse zu liefern, ist NICHT vollständig — Score maximal 0.2.

Antworte als JSON:
{{
    "is_complete": true/false,
    "score": 0.0-1.0,
    "missing_aspects": ["Aspekt 1", "Aspekt 2"],
    "feedback_for_retry": "Konkretes Feedback was fehlt und wie nachgebessert werden soll",
    "output_is_theoretical": true/false
}}"""

        response = await self.llm.chat(
            messages=[
                {"role": "system", "content": "Du bist ein strenger Qualitätsprüfer. Antworte nur mit JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=500,
        )

        result = self._parse_result(response.content)
        return result

    def _detect_capability_gaps(self, output: str) -> list[str]:
        """Erkennt explizite Unfähigkeits-Signale im Output."""
        output_lower = output.lower()
        found = []
        for pattern in CAPABILITY_GAP_PATTERNS:
            if pattern in output_lower:
                found.append(pattern)
        return found

    def _parse_result(self, content: str) -> VerificationResult:
        """Parsed Verification-Antwort."""
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                score = data.get("score", 0.0)
                is_theoretical = data.get("output_is_theoretical", False)
                result = VerificationResult(
                    is_complete=data.get("is_complete", False),
                    score=score,
                    missing_aspects=data.get("missing_aspects", []),
                    feedback_for_retry=data.get("feedback_for_retry", ""),
                )
                if score <= 0.2 and is_theoretical:
                    result.capability_gap = True
                    result.gap_indicators = ["Output ist rein theoretisch / beschreibend"]
                return result
            except json.JSONDecodeError:
                logger.warning("Verification-JSON konnte nicht geparsed werden")
        return VerificationResult(is_complete=True, score=1.0)
