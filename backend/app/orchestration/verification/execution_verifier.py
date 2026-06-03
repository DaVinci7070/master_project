import json
import logging
import re

from app.core.config import settings as default_settings
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

COT_VERIFICATION_PROMPT = """Prüfe systematisch ob dieser Output die Aufgabe vollständig beantwortet.

## Aufgabe
{challenge_text}

## Output
{final_output}

## Analyse-Schritte (führe JEDEN Schritt aus)

### Schritt 1: Teilaspekte identifizieren
Zerlege die Aufgabe in 3-6 bewertbare Teilaspekte. Zum Beispiel:
- Datenquelle korrekt angesprochen?
- Verarbeitung/Transformation durchgeführt?
- Ausgabeformat wie gefordert?
- Vollständigkeit der Ergebnisse?

### Schritt 2: Pro Teilaspekt bewerten
Für JEDEN Teilaspekt:
- Status: VORHANDEN / TEILWEISE / FEHLEND
- Evidenz: Zitiere die relevante Stelle aus dem Output (oder "keine Evidenz")
- Score: 0.0-1.0 für diesen Aspekt

### Schritt 3: Theoretisch vs. Konkret
- Enthält der Output ECHTE DATEN (Zahlen, Namen, Ergebnisse)?
- Oder nur BESCHREIBUNGEN wie man sie bekommen könnte (Vorschläge, Schemas)?
- Ein rein theoretischer Output bekommt maximal Score 0.2 unabhängig von der Analyse.

### Schritt 4: Gesamt-Score berechnen
- Durchschnitt der Teilaspekt-Scores
- Abzug wenn Output theoretisch statt konkret ist
- Abzug wenn kritische Aspekte fehlen (nicht alle Aspekte sind gleich wichtig)

Antworte als JSON:
{{
    "aspects": [
        {{
            "name": "Teilaspekt-Name",
            "status": "VORHANDEN|TEILWEISE|FEHLEND",
            "evidence": "Zitat oder 'keine Evidenz'",
            "score": 0.0
        }}
    ],
    "output_is_theoretical": true,
    "reasoning": "2-3 Sätze die den Gesamt-Score begründen",
    "score": 0.0,
    "is_complete": true,
    "missing_aspects": ["was fehlt"],
    "feedback_for_retry": "konkretes Verbesserungs-Feedback"
}}"""

SINGLE_SHOT_PROMPT = """Prüfe ob dieser Output die Aufgabe vollständig beantwortet.

## Aufgabe
{challenge_text}

## Output
{final_output}

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
    "is_complete": true,
    "score": 0.0,
    "missing_aspects": ["Aspekt 1", "Aspekt 2"],
    "feedback_for_retry": "Konkretes Feedback was fehlt und wie nachgebessert werden soll",
    "output_is_theoretical": true
}}"""

SELF_REFLECTION_PROMPT = """Du hast gerade eine Execution bewertet. Reflektiere über deine eigene Bewertung.

## Deine Bewertung
Score: {score}
Teilaspekt-Scores: {aspect_scores}
Begründung: {reasoning}

## Reflexions-Fragen
1. Ist mein Gesamt-Score konsistent mit den Teilaspekt-Scores?
   (z.B. wenn 4/5 Aspekte Score > 0.8 haben, sollte der Gesamt-Score nicht 0.4 sein)
2. Habe ich einen Aspekt zu streng oder zu milde bewertet?
3. Habe ich den Unterschied zwischen "teilweise" und "fehlend" korrekt eingestuft?
4. Passt der Score zur Aufgaben-Komplexität?

Antworte als JSON:
{{
    "reflection": "Was fällt mir bei der Überprüfung auf?",
    "score_adjustment_needed": true,
    "corrected_score": 0.0,
    "correction_reason": "Warum korrigiert (oder warum nicht)"
}}"""


class ExecutionVerifier:
    """
    Prüft ob Execution-Ergebnisse die Challenge vollständig beantworten.
    Erkennt den Unterschied zwischen "unvollständig" und "grundsätzlich unfähig".
    """

    def __init__(self, llm_client, settings=None):
        self.llm = llm_client
        self._settings = settings or default_settings
        self._reflection_token_count: int = 0
        self._last_tokens_used: int = 0

    async def verify(
        self,
        final_output: str,
        challenge_text: str,
    ) -> VerificationResult:
        """
        Prüft Vollständigkeit und erkennt Capability-Gaps.

        Zwei Prüfungen:
        1. Pattern-Match: Erkennt explizite Unfähigkeits-Signale im Output
        2. LLM-Bewertung: CoT oder Single-Shot je nach Config
        """
        self._reflection_token_count = 0
        self._last_tokens_used = 0

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

        if self._settings.cot_verification_enabled:
            prompt = COT_VERIFICATION_PROMPT.format(
                challenge_text=challenge_text,
                final_output=final_output[:4000],
            )
        else:
            prompt = SINGLE_SHOT_PROMPT.format(
                challenge_text=challenge_text,
                final_output=final_output[:4000],
            )

        response = await self.llm.chat(
            messages=[
                {"role": "system", "content": "Du bist ein strenger Qualitätsprüfer. Antworte nur mit JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=800,
        )
        self._last_tokens_used += response.usage.get("total_tokens", 0)

        result = self._parse_result(response.content)

        if self._settings.cot_verification_enabled:
            result = await self._maybe_self_reflect(result)

        return result

    async def _maybe_self_reflect(self, result: VerificationResult) -> VerificationResult:
        """Self-Reflection nur bei Grenzfällen — spart Tokens bei klaren Ergebnissen."""
        if not self._settings.self_reflection_enabled:
            return result

        margin = self._settings.self_reflection_margin
        thresholds = [
            self._settings.adapt_threshold_new_team,
            self._settings.verification_completeness_threshold,
        ]

        near_threshold = any(abs(result.score - t) <= margin for t in thresholds)
        if not near_threshold:
            return result

        response = await self.llm.chat(
            messages=[
                {"role": "system", "content": "Du reflektierst über deine eigene Bewertung. Sei selbstkritisch."},
                {"role": "user", "content": SELF_REFLECTION_PROMPT.format(
                    score=result.score,
                    aspect_scores=result.aspect_scores,
                    reasoning=result.reasoning_chain,
                )},
            ],
            temperature=0.1,
            max_tokens=400,
        )

        self._reflection_token_count = response.usage.get("total_tokens", 0)
        self._last_tokens_used += self._reflection_token_count

        match = re.search(r"\{.*\}", response.content, re.DOTALL)
        if not match:
            return result

        try:
            reflection_data = json.loads(match.group())
        except json.JSONDecodeError:
            return result

        result.self_reflection = reflection_data.get("reflection", "")

        if reflection_data.get("score_adjustment_needed"):
            corrected = reflection_data.get("corrected_score")
            if corrected is not None and 0.0 <= corrected <= 1.0:
                result.original_score = result.score
                result.score = corrected
                result.score_corrected = True
                result.is_complete = corrected >= self._settings.verification_completeness_threshold

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
        """Parsed Verification-Antwort (CoT oder Single-Shot)."""
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                score = data.get("score", 0.0)
                is_theoretical = data.get("output_is_theoretical", False)

                aspect_scores = {}
                reasoning_chain = data.get("reasoning", "")
                for aspect in data.get("aspects", []):
                    name = aspect.get("name", "")
                    if name:
                        aspect_scores[name] = aspect.get("score", 0.0)

                result = VerificationResult(
                    is_complete=data.get("is_complete", False),
                    score=score,
                    missing_aspects=data.get("missing_aspects", []),
                    feedback_for_retry=data.get("feedback_for_retry", ""),
                    aspect_scores=aspect_scores,
                    reasoning_chain=reasoning_chain,
                )
                if score <= 0.2 and is_theoretical:
                    result.capability_gap = True
                    result.gap_indicators = ["Output ist rein theoretisch / beschreibend"]
                return result
            except json.JSONDecodeError:
                logger.warning("Verification-JSON konnte nicht geparsed werden")
        return VerificationResult(is_complete=True, score=1.0)
