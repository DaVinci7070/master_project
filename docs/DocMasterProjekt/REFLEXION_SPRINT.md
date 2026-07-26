# Reflexion-Sprint: CoT + Self-Reflection Integration in Lumari

> **Grundlage:** Shinn et al. (2023) — *Reflexion: Language Agents with Verbal Reinforcement Learning*
>
> **Kernidee:** Statt Gewichts-Updates nutzt Reflexion verbales Feedback als "semantischen Gradienten".
> Drei Komponenten: Actor (erzeugt Output) → Evaluator (bewertet) → Self-Reflection (reflektiert verbal über Fehler → episodic memory für nächsten Trial).
> In Lumari übertragen wir das Reflexion-Pattern nicht nur auf den Actor (Agents), sondern auch auf den **Evaluator** (ExecutionVerifier) und den **Planner** (TeamAssembler) — ein Beitrag über das Paper hinaus.

---

## Übersicht

| Sprint | Fokus | Dateien | Aufwand | Token-Overhead |
|--------|-------|---------|---------|----------------|
| **S0** | Tag-Filter Bug im Qdrant-Adapter | `qdrant_adapter.py` | ~30min | 0 |
| **S1** | CoT-Scoring im ExecutionVerifier | `execution_verifier.py`, `team_schemas.py` | ~2h | +400-600/Verification |
| **S2** | LLM-Reflexion im FailureAnalyzer | `failure_analyzer.py` | ~1.5h | +300-500/Failure |
| **S3** | CoT im FeasibilityJudge | `feasibility_judge.py` | ~1h | +200/Check |
| **S4** | Episodic Reflection Memory | `strategy_memory.py`, `team_assembler.py`, `config.py` | ~4h | +500/Execution (einmalig) |

**Gesamtaufwand:** ~9-10 Stunden
**Token-Overhead pro kompletter Execution:** ~1.500-2.000 Tokens (bei einem Adapt-Round)

---

## Sprint 0: Tag-Filter Bug im Qdrant-Adapter (BLOCKER für S4)

### Problem

`qdrant_adapter.py:search_facts()` akzeptiert den Parameter `tags: Optional[list[str]]` (Zeile 151), baut ihn aber **nie in den Qdrant-Filter ein** (Zeile 172-187). Der Parameter wird ignoriert.

Das bedeutet: `SharedMemoryQuery(tags=["execution_reflection"])` filtert aktuell NICHT — die Query gibt alle semantisch ähnlichen Facts zurück, unabhängig vom Tag. Sprint 4 braucht aber exakten Tag-Filter, um Reflexionen von Outcomes zu trennen.

### Ist-Zustand

```python
# qdrant_adapter.py:172-187
must_conditions = []
if min_confidence > 0:
    must_conditions.append(...)
if agent_id:
    must_conditions.append(...)
if project_id:
    must_conditions.append(...)
# tags wird NIE geprüft!
query_filter = Filter(must=must_conditions) if must_conditions else None
```

### Fix

```python
# qdrant_adapter.py:172-187 — tags-Filter einbauen
must_conditions = []
if min_confidence > 0:
    must_conditions.append(
        FieldCondition(key="confidence", range=Range(gte=min_confidence))
    )
if agent_id:
    must_conditions.append(
        FieldCondition(key="source_agent_id", match=MatchValue(value=agent_id))
    )
if project_id:
    must_conditions.append(
        FieldCondition(key="project_id", match=MatchValue(value=project_id))
    )
if tags:
    # MatchAny: Fact muss mindestens einen der angegebenen Tags haben
    must_conditions.append(
        FieldCondition(key="tags", match=MatchAny(any=tags))
    )

query_filter = Filter(must=must_conditions) if must_conditions else None
```

**Import hinzufügen:**
```python
from qdrant_client.models import MatchAny  # zusätzlich zu MatchValue
```

### Test

```python
async def test_tag_filter_returns_only_matching():
    """Suche mit Tag-Filter gibt nur Facts mit dem Tag zurück."""
    # Fact mit Tag speichern
    await adapter.upsert_fact(embedding=[...], text="Reflexion...", tags=["execution_reflection"], ...)
    await adapter.upsert_fact(embedding=[...], text="Outcome...", tags=["execution_outcome"], ...)

    # Suche mit Tag-Filter
    results = await adapter.search_facts(
        query_embedding=[...], tags=["execution_reflection"]
    )
    assert all("execution_reflection" in r["tags"] for r in results)
```

---

## Sprint 1: CoT-Scoring + Self-Reflection im ExecutionVerifier

### Motivation

Der ExecutionVerifier (`orchestration/verification/execution_verifier.py:57-82`) nutzt einen Single-Shot LLM-Call der direkt einen 0.0-1.0 Score ausgibt. Das LLM nennt eine Zahl ohne vorher strukturiert nachzudenken — die Scores driften zwischen Runs und korrelieren schlecht mit der tatsächlichen Output-Qualität.

**Problem-Evidenz:** Scores nahe der Thresholds (0.4, 0.85) in `adapt_strategy.py:51-53` führen zu zufälligen Eskalationsentscheidungen. Ein Output der bei Run A Score 0.43 bekommt (→ REPLAN_NEW_TEAM) könnte bei Run B Score 0.38 bekommen (→ selbe Aktion) oder 0.82 (→ REPLAN_FEEDBACK). Die AdaptStrategy-Logik ist solide, aber ihr Input ist zu instabil.

### Ist-Zustand

```
orchestration/verification/execution_verifier.py:57-82
├── Ein Prompt: "Prüfe ob Output die Aufgabe vollständig beantwortet"
├── 4 Prüfkriterien als Fließtext (keine strukturierte Einzelbewertung)
├── Direkte JSON-Antwort: {score, is_complete, missing_aspects, feedback_for_retry}
└── Kein Reasoning-Schritt vor dem Score
```

**Schwächen:**
1. Score und Reasoning sind nicht gekoppelt — LLM kann "3 von 5 Aspekten fehlen" schreiben und trotzdem 0.7 vergeben
2. `output_is_theoretical` ist ein binäres Nachfrage-Feld statt eines Analyse-Schritts
3. Keine Self-Consistency: ein einzelner Call, kein Abgleich

### Soll-Zustand

Zwei-Phasen-Verification mit erzwungenem Chain-of-Thought:

```
Phase A: CoT-Evaluation (ersetzt aktuellen Prompt)
├── Schritt 1: Aufgabe in Teilaspekte zerlegen (z.B. "Datenextraktion", "Formatierung", "Vollständigkeit")
├── Schritt 2: Pro Teilaspekt — vorhanden/fehlend/teilweise + Evidenz aus Output ZITIEREN
├── Schritt 3: Konkret vs. Theoretisch — enthält der Output echte Daten oder nur Beschreibungen?
├── Schritt 4: Score pro Teilaspekt (0.0-1.0) → gewichteter Gesamt-Score
└── Ergebnis: Score folgt deterministisch aus der Analyse

Phase B: Self-Reflection (optionaler 2. LLM-Call, nur bei Grenzfällen)
├── Aktivierung: Score liegt in [threshold - 0.1, threshold + 0.1] für Thresholds (0.4, 0.85)
├── Prompt: "Ist mein Score konsistent mit meiner Teilaspekt-Analyse?"
├── Kann Score nach oben ODER unten korrigieren
└── Begründung für Korrektur wird im VerificationResult gespeichert
```

### Änderungen

#### 1. VerificationResult erweitern (`models/schemas/team_schemas.py:57-64`)

```python
class VerificationResult(BaseModel):
    """Ergebnis der Execution-Verification."""
    is_complete: bool
    score: float = 0.0
    missing_aspects: list[str] = []
    feedback_for_retry: str = ""
    capability_gap: bool = False
    gap_indicators: list[str] = []
    # NEU: CoT-Felder
    aspect_scores: dict[str, float] = {}          # {"datenextraktion": 0.9, "formatierung": 0.3}
    reasoning_chain: str = ""                      # Vollständige CoT-Begründung
    self_reflection: str = ""                      # Optional: Self-Reflection Text
    score_corrected: bool = False                  # True wenn Self-Reflection den Score korrigiert hat
    original_score: float | None = None            # Score vor Korrektur (nur wenn corrected=True)
```

#### 2. CoT-Prompt ersetzen (`orchestration/verification/execution_verifier.py:57-82`)

Aktuellen Prompt (Zeile 57-82) ersetzen durch strukturierten CoT-Prompt:

```python
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
            "score": 0.0-1.0
        }}
    ],
    "output_is_theoretical": true/false,
    "reasoning": "2-3 Sätze die den Gesamt-Score begründen",
    "score": 0.0-1.0,
    "is_complete": true/false,
    "missing_aspects": ["was fehlt"],
    "feedback_for_retry": "konkretes Verbesserungs-Feedback"
}}"""
```

#### 3. Self-Reflection Methode hinzufügen (`execution_verifier.py`)

```python
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
    "score_adjustment_needed": true/false,
    "corrected_score": 0.0-1.0,
    "correction_reason": "Warum korrigiert (oder warum nicht)"
}}"""
```

Neue Methode `_maybe_self_reflect()` — nur aufrufen wenn Score nahe an einem **entscheidungsrelevanten** Threshold liegt:

```python
async def _maybe_self_reflect(
    self,
    result: VerificationResult,
    margin: float | None = None,
) -> VerificationResult:
    """Self-Reflection nur bei Grenzfällen — spart Tokens bei klaren Ergebnissen.

    Thresholds kommen aus config: adapt_threshold_new_team (0.4),
    verification_completeness_threshold (0.85).
    """
    if not self._settings.self_reflection_enabled:
        return result

    _margin = margin or self._settings.self_reflection_margin
    thresholds = [
        self._settings.adapt_threshold_new_team,       # 0.4
        self._settings.verification_completeness_threshold,  # 0.85
    ]

    near_threshold = any(
        abs(result.score - t) <= _margin for t in thresholds
    )
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

    reflection_data = self._parse_json(response.content)
    result.self_reflection = reflection_data.get("reflection", "")

    if reflection_data.get("score_adjustment_needed"):
        result.original_score = result.score
        result.score = reflection_data["corrected_score"]
        result.score_corrected = True

    # Token-Tracking für Observability
    self._reflection_token_count = getattr(response, "usage", {}).get("total_tokens", 0)

    return result
```

**Begründung für Threshold-Änderung:** Der alte Plan hatte `[0.1, 0.4, 0.85]`. Der 0.1-Threshold (`adapt_threshold_escalate`) ist irrelevant für Self-Reflection:
- Score < 0.1 bedeutet "grundlegende Fähigkeiten fehlen" → ESCALATE
- Ob der Score 0.05 oder 0.15 ist, ändert nichts an der Entscheidung (beides → ESCALATE bzw. REPLAN_NEW_TEAM)
- Self-Reflection bei offensichtlich schlechten Ergebnissen verschwendet Tokens ohne Entscheidungs-Impact

Die relevanten Grenzentscheidungen sind nur:
- 0.4 ± 0.1: REPLAN_NEW_TEAM vs. REPLAN_FEEDBACK
- 0.85 ± 0.1: REPLAN_FEEDBACK vs. PASS

#### 4. Config-Flags (`config.py`)

```python
# Reflexion Sprint — Phase 1: CoT Verification
cot_verification_enabled: bool = True              # CoT statt Single-Shot im Verifier
self_reflection_enabled: bool = True               # Self-Reflection bei Grenzfällen
self_reflection_margin: float = 0.1                # Abstand zum Threshold für Aktivierung
```

#### 5. Constructor erweitern

```python
class ExecutionVerifier:
    def __init__(self, llm_client, settings=None):
        self.llm = llm_client
        self._settings = settings or get_settings()
        self._reflection_token_count: int = 0  # Tracking für Observability
```

### Tests

```python
# test_execution_verifier.py
async def test_cot_scoring_produces_aspect_scores():
    """CoT-Prompt erzeugt Score pro Teilaspekt."""
    result = await verifier.verify(final_output="...", challenge_text="...")
    assert len(result.aspect_scores) >= 3
    assert all(0.0 <= s <= 1.0 for s in result.aspect_scores.values())

async def test_score_consistent_with_aspects():
    """Gesamt-Score weicht maximal 0.15 vom Aspekt-Durchschnitt ab."""
    result = await verifier.verify(...)
    avg = sum(result.aspect_scores.values()) / len(result.aspect_scores)
    assert abs(result.score - avg) <= 0.15

async def test_self_reflection_activates_near_threshold():
    """Self-Reflection nur bei Scores nahe Thresholds (0.4, 0.85)."""
    # Mock LLM der Score 0.42 zurückgibt (nahe 0.4-Threshold)
    result = await verifier.verify(...)
    assert result.self_reflection != ""  # Wurde aktiviert

async def test_self_reflection_skips_clear_results():
    """Kein Self-Reflection bei Score 0.7 (weit von allen Thresholds)."""
    result = await verifier.verify(...)
    assert result.self_reflection == ""
    assert result.score_corrected is False

async def test_no_self_reflection_at_score_01():
    """Kein Self-Reflection bei Score nahe 0.1 — ESCALATE ist ohnehin klar."""
    # Mock LLM der Score 0.12 zurückgibt
    result = await verifier.verify(...)
    assert result.self_reflection == ""  # Nicht aktiviert

async def test_theoretical_output_capped_at_02():
    """Rein theoretischer Output maximal 0.2 Score."""
    theoretical_output = "Man könnte folgendes SQL-Schema verwenden..."
    result = await verifier.verify(final_output=theoretical_output, ...)
    assert result.score <= 0.2
```

### Ablation

- `cot_verification_enabled=False` → alter Single-Shot-Prompt (Baseline)
- `self_reflection_enabled=False` → CoT ohne Reflexion (isoliert CoT-Effekt)
- Beide `True` → volle Reflexion (Hauptvariante)

**Messbar:** Score-Varianz über 10 identische Runs derselben Challenge. Erwartung: CoT reduziert Varianz um 40-60%.

---

## Sprint 2: LLM-Reflexion im FailureAnalyzer

### Motivation

`FailureAnalyzer.lesson_learned` (`feedback_loop/analysis/failure_analyzer.py:244-249`) wird aktuell per String-Concat befüllt:

```python
analysis.lesson_learned = (
    f"{analysis.error_type_classified}: {analysis.root_cause[:150]}. "
    f"Fix: {analysis.suggested_fixes[0]}"
)
# Ergebnis: "IMPORT_ERROR: Missing module: pandas. Fix: Install package: pandas"
```

Das ist mechanisch und wiederholend — kein echtes Lernen. Der LLM-Client ist bereits injected (`failure_analyzer.py:148`, `self.llm`) aber wird nie für Reflexion genutzt. Die Pipeline ist schon verdrahtet: `format_failure_context()` gibt `lesson_learned` an den nächsten Build weiter. Die Qualität der Lessons ist nur schlecht.

### Ist-Zustand

```
analyze_failure() → classify_error() → _analyze_{type}_error() → lesson_learned = String-Concat
                                                                 ↓
format_failure_context() → "Lesson: IMPORT_ERROR: Missing module: pandas..."
                                                                 ↓
Nächster Build-Versuch bekommt diesen Text als Kontext → nicht hilfreich
```

### Soll-Zustand

```
analyze_failure() → classify_error() → _analyze_{type}_error()
                                         ↓
                                    _generate_reflection(code, error, context)
                                         ↓
                    "Der Versuch hat pandas.read_csv() genutzt, aber im
                     Sandbox-Container ist nur stdlib. Der Fehler war nicht
                     der Algorithmus sondern die Dependency-Wahl. Nächster
                     Versuch: csv.reader() aus stdlib, Spalten manuell parsen."
                                         ↓
format_failure_context() → brauchbare Reflexion für nächsten Build
```

### Änderungen

#### 1. Reflexions-Methode hinzufügen (`feedback_loop/analysis/failure_analyzer.py`)

Nach Zeile 260, vor dem Return von `analyze_failure()`:

```python
FAILURE_REFLECTION_PROMPT = """Reflektiere über diesen fehlgeschlagenen Skill-Build-Versuch.

## Capability
{capability}

## Code (Ausschnitt)
```python
{code_excerpt}
```

## Fehler
Typ: {error_type}
Nachricht: {error_message}

## Programmatische Analyse
Root Cause: {root_cause}
Vorgeschlagene Fixes: {suggested_fixes}

## Reflexions-Aufgabe
Schreibe eine KONKRETE Reflexion (2-3 Sätze) die dem nächsten Build-Versuch hilft.
Fokussiere auf:
1. Was war die EIGENTLICHE Ursache (nicht nur das Symptom)?
2. Was sollte der nächste Versuch ANDERS machen?
3. Welche ALTERNATIVE Strategie wäre besser gewesen?

Schreibe die Reflexion in der Ich-Form, als würde der Builder aus seinem Fehler lernen.
Keine Wiederholung der Fehlermeldung — die kennt der nächste Builder schon."""
```

```python
async def _generate_reflection(
    self,
    capability: str,
    code: str,
    error_message: str,
    analysis: FailureAnalysis,
) -> str:
    """LLM-basierte Reflexion über einen fehlgeschlagenen Build-Versuch."""
    if not self.llm or not self._settings.failure_reflection_enabled:
        return self._format_programmatic_lesson(analysis)

    prompt = FAILURE_REFLECTION_PROMPT.format(
        capability=capability,
        code_excerpt=code[:1500],
        error_type=analysis.error_type.value,
        error_message=error_message[:300],
        root_cause=analysis.root_cause,
        suggested_fixes=", ".join(analysis.suggested_fixes[:3]),
    )

    try:
        response = await self.llm.chat(
            messages=[
                {"role": "system", "content": "Du reflektierst über Build-Fehler. Kurz, konkret, hilfreich."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=200,
        )
        return response.content.strip()
    except Exception as e:
        logger.warning(f"Reflexion-Generation fehlgeschlagen: {e}")
        return self._format_programmatic_lesson(analysis)

def _format_programmatic_lesson(self, analysis: FailureAnalysis) -> str:
    """Fallback: Mechanische lesson_learned wie bisher."""
    if analysis.suggested_fixes:
        return (
            f"{analysis.error_type_classified}: {analysis.root_cause[:150]}. "
            f"Fix: {analysis.suggested_fixes[0]}"
        )
    return f"{analysis.error_type_classified}: {analysis.root_cause[:200]}"
```

#### 2. In `analyze_failure()` einbinden (`failure_analyzer.py:243-249`)

Zeile 243-249 ersetzen:

```python
# Statt String-Concat → LLM-Reflexion
analysis.error_type_classified = self.classify_error_coarse(error_type)
analysis.lesson_learned = await self._generate_reflection(
    capability=capability,
    code=code,
    error_message=error_message,
    analysis=analysis,
)
```

#### 3. Config-Flag (`config.py`)

```python
# Reflexion Sprint — Phase 2: Failure Reflexion
failure_reflection_enabled: bool = True   # LLM-Reflexion statt String-Concat
```

### Tests

```python
async def test_reflection_is_not_error_echo():
    """Reflexion enthält nicht einfach die Fehlermeldung nochmal."""
    analysis = await analyzer.analyze_failure(
        capability="csv_parsing",
        code="import pandas as pd\n...",
        error_message="ModuleNotFoundError: No module named 'pandas'",
    )
    # Reflexion sollte NICHT einfach "ModuleNotFoundError" wiederholen
    assert "ModuleNotFoundError" not in analysis.lesson_learned
    # Sondern alternative Strategie vorschlagen
    assert any(kw in analysis.lesson_learned.lower() for kw in ["csv", "stdlib", "alternativ", "stattdessen"])

async def test_reflection_fallback_without_llm():
    """Ohne LLM-Client → programmatischer Fallback."""
    analyzer_no_llm = FailureAnalyzer(session_factory=sf, llm_client=None)
    analysis = await analyzer_no_llm.analyze_failure(...)
    assert analysis.lesson_learned != ""  # Fallback greift

async def test_reflection_fallback_when_disabled():
    """Mit Flag disabled → programmatischer Fallback trotz LLM."""
    settings.failure_reflection_enabled = False
    analysis = await analyzer.analyze_failure(...)
    # Fallback-Format: "TYPE: root_cause. Fix: ..."
    assert ":" in analysis.lesson_learned
```

---

## Sprint 3: CoT im FeasibilityJudge

### Motivation

Der `FEASIBILITY_PROMPT` (`orchestration/analysis/feasibility_judge.py:23-51`) fragt direkt nach einem `feasible: true/false` Verdict. Bei komplexen Capabilities die **mehrere I/O-Operationen** kombinieren (z.B. "CSV lesen und in Datenbank schreiben") urteilt das LLM zu schnell — es sieht z.B. einen DB-Skill und sagt "feasible", obwohl der File-Reading-Teil fehlt.

### Ist-Zustand

```
FEASIBILITY_PROMPT → 5 Regeln als Fließtext → direkt JSON {feasible, tool_name, reason}
```

### Soll-Zustand

```
FEASIBILITY_PROMPT → Reasoning-Schritte erzwingen → dann Verdict
```

### Änderungen

#### 1. Prompt erweitern (`feasibility_judge.py:23-51`)

`FEASIBILITY_PROMPT` ersetzen. **Komplett Englisch** (konsistent mit bestehendem Prompt, LLMs performen besser bei einsprachigen Prompts):

```python
FEASIBILITY_PROMPT = """You are verifying whether an agent can actually perform a SPECIFIC action.

## Required Action
{action}

## Agent: {agent_name}
Capabilities declared: {agent_capabilities}

## Agent System Prompt (excerpt)
{agent_prompt_excerpt}

## Available Tools/Skills bound to this agent:
{skill_list}

## Analysis Steps (execute EACH step before judging)

### Step 1: Decompose the action
Break the required action into individual operations.
Example: "Read CSV and write to database" → [1. Read file, 2. Parse data, 3. Write to DB]

### Step 2: I/O type per operation
For each operation: What I/O type is needed?
- REASONING (text analysis, summarization) → no tool needed if prompt covers domain
- FILE_IO (read/write files) → needs File skill
- DATABASE (SQL, queries) → needs DB skill
- API_CALL (external services) → needs HTTP/API skill
- CODE_EXECUTION (computations) → needs Execution skill

### Step 3: Tool matching
For each operation that needs a tool: Is there a SPECIFIC tool in the list?
- A DB tool does NOT cover file I/O (and vice versa)
- A "general" skill is not enough — the skill must cover the SPECIFIC operation
- "Transform and load data" requires BOTH reading the source AND writing to the target

### Step 4: Verdict
- Feasible ONLY if ALL operations are covered
- Infeasible if even ONE operation has no matching tool

Respond with JSON only, no markdown:
{{"reasoning_steps": ["Step 1: ...", "Step 2: ...", "Step 3: ...", "Step 4: ..."], "feasible": true/false, "tool_name": "name of specific tool or null", "reason": "brief conclusion"}}"""
```

#### 2. Response-Schema erweitern (`orchestration/analysis/models.py` oder inline)

```python
class FeasibilityLLMResponse(BaseModel):
    reasoning_steps: list[str] = []   # NEU: CoT-Schritte
    feasible: bool
    tool_name: str | None = None
    reason: str
```

#### 3. FeasibilityResult erweitern

```python
class FeasibilityResult(BaseModel):
    required_capability: str
    matched_agent_id: str
    feasible: bool
    tool_name: str | None = None
    reason: str
    reasoning_steps: list[str] = []   # NEU: transparente Begründung
```

### Tests

```python
async def test_multi_operation_infeasible():
    """Capability mit 2 I/O-Typen → infeasible wenn nur 1 Tool da ist."""
    # Agent hat DB-Skill aber keinen File-I/O-Skill
    result = await judge._judge_single(CapabilityMatch(
        required_capability="CSV-Datei einlesen und in PostgreSQL speichern",
        matched_agent_id="data_agent",
        capability_type=CapabilityType.EXECUTION,
    ))
    assert not result.feasible
    assert len(result.reasoning_steps) >= 3

async def test_reasoning_only_feasible_without_tools():
    """Reine Reasoning-Aufgabe → feasible auch ohne Skills."""
    result = await judge._judge_single(CapabilityMatch(
        required_capability="Text zusammenfassen und Kernaussagen extrahieren",
        ...
    ))
    assert result.feasible
```

---

## Sprint 4: Episodic Reflection Memory

### Motivation

Das ist die **eigentliche Reflexion-Innovation aus dem Paper**. Sprints 1-3 sind CoT/Self-Reflection (verbessern einzelne Entscheidungen). Sprint 4 ist **episodisches Lernen über Trials hinweg** — genau das was in Shinn et al. die 22% Verbesserung in AlfWorld und 11% in HumanEval gebracht hat.

Aktuell speichert `StrategyMemory` (`orchestration/execution/strategy_memory.py:44-57`) nur Fakten:
```
"Challenge-Typ: database. Strategie: keine angegeben. Team: agent_a, agent_b. Score: 0.42. GESCHEITERT."
```

Das ist ein Logbuch, keine Reflexion. Der TeamAssembler liest diese Fakten (`team_assembler.py:326-354`) und kann daraus nur ableiten "die alte Strategie war schlecht". Aber nicht WARUM und was STATTDESSEN besser wäre.

### Soll-Zustand

Nach jeder Execution generiert ein LLM-Call eine strukturierte Reflexion:

```
"Challenge 'ETL Pipeline aus CSV in PostgreSQL' scheiterte mit Score 0.42.
Ursache: Der data_processor Agent hatte einen DB-Skill aber keinen File-I/O-Skill.
Die CSV-Daten konnten nicht eingelesen werden. Der FeasibilityJudge hat das nicht
erkannt weil er nur den DB-Skill geprüft hat.
Nächstes Mal: Team muss einen Agent mit File-Lese-Fähigkeit UND einen mit DB-Schreib-
Fähigkeit enthalten. Alternativ: Einen Agent mit ETL-Skill der beides kann."
```

Diese Reflexion wird **separat** vom Outcome-Fact gespeichert (eigener Tag `execution_reflection`) und beim nächsten `TeamAssembler.assemble_team()` als Kontext geladen (max 3, wie im Paper §3: Ω = 1-3).

### Voraussetzung: Sprint 0 (Tag-Filter Fix)

Sprint 4 ist **nicht umsetzbar** ohne den Tag-Filter-Fix aus Sprint 0. Ohne ihn gibt `SharedMemoryQuery(tags=["execution_reflection"])` trotzdem alle Facts zurück.

### Reflexion-Decay-Strategie

**Problem:** Nach 50 gescheiterten Executions existieren 50 Reflexionen. `max_items=3` gibt die semantisch ähnlichsten zurück — aber alte Reflexionen können obsolet sein (z.B. "File-I/O-Skill fehlt" obwohl der inzwischen gebaut wurde).

**Lösung: Confidence-Decay + Success-Invalidation**

1. Reflexionen werden mit `confidence=0.7` gespeichert (nicht 1.0)
2. Bei **Erfolg** einer Challenge desselben Typs: Verwandte Reflexionen werden per `supersedes_id` als gelöst markiert (Confidence → 0.1)
3. Die Query nutzt `min_confidence=0.3` → veraltete Reflexionen fallen automatisch raus
4. Zusätzlich: `recency_scale=604800` (1 Woche) im Qdrant-Adapter boostet neuere Reflexionen

```python
async def _invalidate_resolved_reflections(
    self,
    challenge_text: str,
    execution_id: str,
) -> None:
    """Bei Erfolg: Verwandte Reflexionen als gelöst markieren."""
    if not self.shared_memory or not self.embedding_fn:
        return

    embedding = await self.embedding_fn(challenge_text[:500])
    # Suche Reflexionen die sich auf ähnliche Challenges beziehen
    from app.models.schemas.shared_memory_schemas import SharedMemoryQuery
    query = SharedMemoryQuery(
        query_text=challenge_text[:200],
        max_items=5,
        score_threshold=0.5,  # Nur wirklich ähnliche
        tags=["execution_reflection"],
    )
    context = await self.shared_memory.retrieve_context(query)
    reflections = context.get("facts", [])

    for ref in reflections:
        ref_id = ref.get("id")
        if ref_id:
            # Überschreibe mit Erfolgs-Notiz (niedrige Confidence)
            await self.shared_memory.create_fact(
                fact_data=FactCreate(
                    text=f"[GELÖST] {ref.get('text', '')[:100]}... → Erfolgreich in {execution_id}",
                    confidence=0.1,
                    source_agent_id="strategy_memory_reflection",
                    execution_id=execution_id,
                    project_id=ref.get("project_id", "default"),
                    tags=["execution_reflection", "resolved"],
                    supersedes_id=ref_id,
                ),
                embedding=embedding,
            )
```

### Änderungen

#### 1. Reflexions-Methode in StrategyMemory (`orchestration/execution/strategy_memory.py`)

```python
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
```

#### 2. `record_outcome()` erweitern (`strategy_memory.py:22-77`)

Zwei Facts statt einem + Success-Invalidation:

```python
async def record_outcome(
    self,
    team_plan: "TeamPlan",
    verification_score: float,
    duration_ms: int,
    tokens_total: int,
    adapt_rounds: int = 0,
    execution_id: str = "unknown",
    project_id: str = "default",
    verification_feedback: str = "",  # NEU: Feedback aus VerificationResult
) -> None:
    # ... bestehender Outcome-Fact Code (unverändert) ...

    success = verification_score >= 0.85

    # NEU: Bei Erfolg → verwandte Reflexionen als gelöst markieren
    if success:
        await self._invalidate_resolved_reflections(
            challenge_text=team_plan.challenge_text,
            execution_id=execution_id,
        )
        return  # Outcome-Fact wie bisher speichern (Code oben)

    # NEU: Bei Misserfolg → LLM-Reflexion generieren und separat speichern
    if self._settings.execution_reflection_enabled:
        reflection = await self._generate_execution_reflection(
            team_plan=team_plan,
            verification_score=verification_score,
            verification_feedback=verification_feedback,
        )
        if reflection:
            embedding = None
            if self.embedding_fn:
                embedding = await self.embedding_fn(team_plan.challenge_text[:500])

            await self.shared_memory.create_fact(
                fact_data=FactCreate(
                    text=reflection,
                    confidence=0.7,  # Nicht 1.0 — ermöglicht Decay
                    source_agent_id="strategy_memory_reflection",
                    execution_id=execution_id,
                    project_id=project_id,
                    tags=["execution_reflection"],
                ),
                embedding=embedding,
            )
```

#### 3. Constructor erweitern (`strategy_memory.py:18-20`)

```python
def __init__(self, shared_memory, embedding_fn=None, llm_client=None, settings=None):
    self.shared_memory = shared_memory
    self.embedding_fn = embedding_fn
    self._llm_client = llm_client  # NEU: für Reflexion
    self._settings = settings or get_settings()
```

#### 4. TeamAssembler: Reflexionen laden (`team_assembler.py:326-354`)

Methode `_load_past_experiences()` erweitern — zwei Queries statt einer:

```python
async def _load_past_experiences(self, challenge_text: str) -> str | None:
    if not self.shared_memory:
        return None

    try:
        from app.models.schemas.shared_memory_schemas import SharedMemoryQuery

        # Query 1: Outcomes (wie bisher)
        outcome_query = SharedMemoryQuery(
            query_text=f"team_plan execution strategy: {challenge_text[:200]}",
            max_items=3,
            score_threshold=0.3,
        )
        outcome_context = await self.shared_memory.retrieve_context(outcome_query)

        # Query 2: Reflexionen (NEU) — nur nicht-gelöste (confidence > 0.3)
        reflection_query = SharedMemoryQuery(
            query_text=f"execution reflection lesson: {challenge_text[:200]}",
            max_items=self._settings.reflection_memory_max_items,  # Ω = 3
            score_threshold=0.3,
            min_confidence=0.3,  # Filtert gelöste Reflexionen (confidence=0.1) raus
            tags=["execution_reflection"],
        )
        reflection_context = await self.shared_memory.retrieve_context(reflection_query)

        lines = []

        # Outcomes
        outcomes = outcome_context.get("facts", [])
        if outcomes:
            lines.append("### Frühere Ergebnisse")
            for fact in outcomes[:3]:
                payload = fact.get("text", "") if isinstance(fact, dict) else str(fact)
                lines.append(f"- {payload}")

        # Reflexionen (gewichtet stärker — das sind die actionable Lessons)
        reflections = reflection_context.get("facts", [])
        if reflections:
            lines.append("\n### Reflexionen aus gescheiterten Versuchen (BEACHTE DIESE!)")
            for fact in reflections[:3]:
                payload = fact.get("text", "") if isinstance(fact, dict) else str(fact)
                lines.append(f"- {payload}")

        return "\n".join(lines) if lines else None

    except Exception as e:
        logger.warning(f"SharedMemory-Abfrage fehlgeschlagen: {e}")
        return None
```

#### 5. `verification_feedback` durchreichen (`hybrid_orchestrator.py:461-469`)

```python
# hybrid_orchestrator.py, Zeile 461
await self._strategy_memory.record_outcome(
    team_plan=team_plan,
    verification_score=last_score,
    duration_ms=int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000),
    tokens_total=strategy_tokens,
    adapt_rounds=adapt_rounds,
    execution_id=self._execution_id or "unknown",
    project_id=self._project_id,
    verification_feedback=last_verification.feedback_for_retry if last_verification else "",  # NEU
)
```

#### 6. Config-Flags (`config.py`)

```python
# Reflexion Sprint — Phase 4: Episodic Reflection Memory
execution_reflection_enabled: bool = True       # LLM-Reflexion nach Misserfolg
reflection_memory_max_items: int = 3            # Ω = 3 (Paper-Empfehlung)
```

#### 7. DI-Wiring — LLM-Client in StrategyMemory (`api/v1/endpoints/challenges.py:1287-1292`)

Die aktuelle Stelle:
```python
# challenges.py:1287-1292
strategy_memory = StrategyMemory(
    shared_memory=shared_mem_service,
    embedding_fn=embedding_fn,
)
```

Wird zu:
```python
strategy_memory = StrategyMemory(
    shared_memory=shared_mem_service,
    embedding_fn=embedding_fn,
    llm_client=llm,       # NEU: derselbe LLM-Client wie HybridOrchestrator
    settings=app_settings,  # NEU: für Feature-Flags
)
```

### Tests

```python
async def test_reflection_generated_on_failure():
    """Bei Score < 0.85 wird eine Reflexion generiert und gespeichert."""
    await strategy_memory.record_outcome(
        team_plan=plan, verification_score=0.3,
        verification_feedback="File-I/O fehlt komplett", ...
    )
    # Prüfe: 2 Facts in SharedMemory (Outcome + Reflexion)
    facts = await shared_memory.get_all_facts()
    assert len(facts) == 2
    reflection_facts = [f for f in facts if "execution_reflection" in f.tags]
    assert len(reflection_facts) == 1
    assert "File-I/O" in reflection_facts[0].text or "alternativ" in reflection_facts[0].text.lower()

async def test_no_reflection_on_success():
    """Bei Erfolg keine Reflexion (spart Tokens)."""
    await strategy_memory.record_outcome(
        team_plan=plan, verification_score=0.9, ...
    )
    facts = await shared_memory.get_all_facts()
    reflection_facts = [f for f in facts if "execution_reflection" in f.tags]
    assert len(reflection_facts) == 0

async def test_success_invalidates_old_reflections():
    """Bei Erfolg werden verwandte Reflexionen auf confidence=0.1 gesetzt."""
    # Erst Misserfolg → Reflexion wird gespeichert
    await strategy_memory.record_outcome(
        team_plan=plan_fail, verification_score=0.3, ...
    )
    # Dann Erfolg mit ähnlicher Challenge → alte Reflexion wird invalidiert
    await strategy_memory.record_outcome(
        team_plan=plan_success, verification_score=0.9, ...
    )
    # Gelöste Reflexion hat niedrige Confidence
    facts = await shared_memory.get_all_facts()
    resolved = [f for f in facts if "resolved" in f.tags]
    assert len(resolved) == 1

async def test_team_assembler_uses_reflections():
    """TeamAssembler bekommt Reflexionen als Kontext."""
    await shared_memory.create_fact(FactCreate(
        text="ETL scheiterte weil File-I/O-Skill fehlte...",
        confidence=0.7,
        tags=["execution_reflection"], ...
    ))
    experiences = await assembler._load_past_experiences("ETL Pipeline...")
    assert "Reflexionen aus gescheiterten Versuchen" in experiences
    assert "File-I/O-Skill" in experiences

async def test_team_assembler_ignores_resolved_reflections():
    """Gelöste Reflexionen (confidence=0.1) werden nicht geladen."""
    await shared_memory.create_fact(FactCreate(
        text="[GELÖST] ETL scheiterte weil...",
        confidence=0.1,  # Resolved
        tags=["execution_reflection", "resolved"], ...
    ))
    experiences = await assembler._load_past_experiences("ETL Pipeline...")
    assert experiences is None or "GELÖST" not in experiences
```

### E2E-Integrationstest

```python
async def test_reflexion_full_loop():
    """Vollständiger Loop: Scheitern → Reflexion → nächster Versuch nutzt sie."""
    # 1. Challenge scheitert
    result1 = await orchestrator.execute(challenge="ETL: CSV → PostgreSQL")
    assert result1["verification_score"] < 0.85

    # 2. Reflexion wurde gespeichert
    facts = await shared_memory.search_by_tags(["execution_reflection"])
    assert len(facts) >= 1
    reflexion_text = facts[0]["text"]

    # 3. Gleiche Challenge nochmal → TeamAssembler bekommt Reflexion
    # (Mock: prüfe dass der Assembler-Prompt die Reflexion enthält)
    with patch.object(assembler, "_call_llm") as mock_llm:
        await orchestrator.execute(challenge="ETL: CSV → PostgreSQL")
        prompt_sent = mock_llm.call_args[0][0]
        assert reflexion_text[:50] in prompt_sent or "Reflexionen" in prompt_sent
```

### Ablation

- `execution_reflection_enabled=False` → nur Outcome-Facts (Baseline)
- `True` → Reflexion + Outcomes (Hauptvariante)

**Messbar:** Warm-Start Pass-Rate bei wiederholten Challenge-Typen. Erwartung: 10-20% Verbesserung bei Challenges die vorher gescheitert sind (Paper: +22% in AlfWorld über 12 Trials).

---

## Sprint 5: Observability & Token-Tracking

### Motivation

Für die Thesis-Auswertung brauchen wir Antworten auf:
- "Wie oft korrigiert Self-Reflection den Score?" (Sprint 1)
- "Wie viele zusätzliche Tokens kosten die Reflexions-Calls?" (Sprint 1, 2, 4)
- "Werden gespeicherte Reflexionen tatsächlich genutzt?" (Sprint 4)

Ohne Observability können wir die Ablation nicht quantifizieren.

### Änderungen

#### 1. Reflexion-Metrics im ExecutionResult

Im `HybridOrchestrator`-Response ergänzen:

```python
# Im execution_stats dict (hybrid_orchestrator.py:514-518)
execution_stats = {
    ...
    "reflexion_metrics": {
        "cot_verification_used": settings.cot_verification_enabled,
        "self_reflection_triggered": last_verification.score_corrected if last_verification else False,
        "self_reflection_correction": (
            last_verification.original_score - last_verification.score
            if last_verification and last_verification.score_corrected else 0.0
        ),
        "reflection_tokens_verifier": execution_verifier._reflection_token_count if execution_verifier else 0,
        "reflection_memory_stored": bool(...)  # True wenn Reflexion gespeichert wurde
        "reflection_memory_used": bool(...)    # True wenn TeamAssembler Reflexionen geladen hat
    },
}
```

#### 2. Reflexion-Events im SSE-Stream

```python
# Neuer Event-Typ in der SSE-Pipeline
await self._emit_event(
    event_type="reflexion",
    data={
        "phase": "self_reflection",  # oder "failure_reflection", "execution_reflection"
        "score_before": original_score,
        "score_after": corrected_score,
        "tokens_used": token_count,
    }
)
```

#### 3. Benchmark-Runner: Reflexion-Metriken sammeln

Im Benchmark-Runner (`scripts/evaluation/`) die neuen Felder aus `execution_stats["reflexion_metrics"]` in die Ergebnis-CSV schreiben. Ermöglicht:
- Token-Overhead pro Sprint quantifizieren
- Self-Reflection-Korrektur-Rate messen
- Reflexion-Nutzungsrate im Warm-Start messen

---

## Zusammenfassung: Alle Config-Flags

```python
# config.py — Reflexion Sprint

# Sprint 1: CoT Verification
cot_verification_enabled: bool = True
self_reflection_enabled: bool = True
self_reflection_margin: float = 0.1

# Sprint 2: Failure Reflexion
failure_reflection_enabled: bool = True

# Sprint 3: CoT FeasibilityJudge
# (Kein separater Flag — CoT-Prompt ist immer besser, kein Tradeoff)

# Sprint 4: Episodic Reflection Memory
execution_reflection_enabled: bool = True
reflection_memory_max_items: int = 3
```

Alle Flags sind per Default `True` und können für Ablation einzeln deaktiviert werden.

---

## Abhängigkeiten & Reihenfolge

```
S0 (Tag-Filter Fix) ─── Blocker für S4
     │
     ├── S1 (CoT Verifier) ─── unabhängig
     ├── S2 (Failure Reflexion) ─── unabhängig
     ├── S3 (CoT FeasibilityJudge) ─── unabhängig
     │
     └── S4 (Episodic Memory) ─── braucht S0 + verification_feedback aus S1
              │
              └── S5 (Observability) ─── braucht alle Sprints für Metriken
```

**Empfohlene Reihenfolge:** S0 → S1 → S4 → S2 → S3 → S5

Begründung: S0 ist Blocker. S1 liefert `verification_feedback` das S4 nutzt. S4 ist der Kern-Beitrag für die Thesis (RQ1). S2/S3 sind nice-to-have und unabhängig. S5 am Ende wenn alles funktioniert.

---

## Thesis-Relevanz

| Forschungsfrage | Sprint-Beitrag |
|-----------------|----------------|
| **RQ1** (Selbst-Evolution > statisch?) | Sprint 4: Episodisches Lernen = formalisierte Selbst-Evolution über Trials |
| **RQ2** (Wiederverwendung senkt Kosten?) | Sprint 2+4: Bessere Lessons → weniger Fehlversuche → weniger Tokens im Warm-Start |
| **RQ3** (Gatekeeper erkennt Diskrepanzen?) | Sprint 3: CoT im FeasibilityJudge = präzisere Gatekeeper-Entscheidungen |

**Eigener Beitrag über Shinn et al. hinaus:**
Reflexion wird im Paper nur auf der **Actor-Seite** eingesetzt (Agent lernt aus eigenen Fehlern). Lumari überträgt das Pattern auf den **Evaluator** (Sprint 1: Verifier reflektiert über eigene Bewertung) und den **Planner** (Sprint 4: TeamAssembler lernt aus gescheiterten Strategien). Das ist eine Generalisierung von Reflexion auf das gesamte MAS, nicht nur einzelne Agents.

---

## Bekannte Limitationen (für Thesis-Diskussion)

1. **Keine Cross-Execution Parallelität:** Reflexionen werden sequentiell geschrieben. Bei parallelen Executions könnten neueste Reflexionen noch nicht für gleichzeitig laufende Challenges sichtbar sein. In der Praxis irrelevant (Benchmarks sind sequentiell), aber als Limitation zu erwähnen.

2. **Embedding-Qualität bestimmt Reflexions-Retrieval:** Wenn der Embedding-Vektor eines Challenge-Texts schlecht ist (z.B. bei sehr kurzen oder mehrdeutigen Beschreibungen), findet die Vektor-Suche die falsche Reflexion. Mitigation: `score_threshold=0.3` filtert schlechte Matches.

3. **Reflexion-Qualität hängt vom LLM ab:** Die Reflexion ist nur so gut wie das LLM sie generiert. Bei schwachen Modellen (z.B. Haiku) könnten die Reflexionen generisch statt actionable sein. Empfehlung: Reflexions-Calls mit dem stärksten verfügbaren Modell ausführen (konfigurierbar).

4. **Kein Reflexion-Grounding:** Die Reflexion behauptet z.B. "File-I/O-Skill fehlte" — aber es gibt keinen automatischen Check ob das stimmt. Das System vertraut der LLM-Reflexion blind. Mögliche Erweiterung: Reflexion gegen tatsächliche Skill-Liste validieren.