# Lumari System-Analyse

**Datum:** 2026-04-02
**Ziel:** Funktionsfähigkeit für Tests herstellen (keine Production-App)

---

## Projekt-Übersicht

**Lumari** ist ein selbst-evolvierendes Multi-Agent-System: Challenges werden analysiert, Capability-Gaps erkannt, Skills autonom gebaut, und Agents orchestriert. Architektonisch sehr ambitioniert und gut strukturiert - aber einige kritische Stellen verhindern aktuell die Funktionsfähigkeit.

---

## KRITISCH - Muss gefixt werden damit es läuft

### 1. LLM JSON-Parsing bricht überall

**Dateien:** `feasibility_judge.py`, `gap_detector.py`, `challenge_analyzer.py`

LLM-Output wird per Hand geparst. Wenn das LLM Markdown-Codeblöcke zurückgibt (`` ```json ... ``` ``), scheitert das Parsing oft.

**Fix:** Zentrale `parse_json_response()` Utility mit robustem Codeblock-Extraction.

---

### 2. Embedding-Fallback = Zero Vector

**Datei:** `capability_matcher.py:48-58`

Wenn keine Embedding-Funktion konfiguriert ist, werden Zero-Vektoren verwendet. Damit ist **jedes Capability-Matching nutzlos** - alle Agents sehen gleich aus.

**Fix:** Embedding-Funktion muss beim Start validiert oder fastembed als Default eingebunden werden.

---

### 3. Alembic importiert nicht alle Models

**Datei:** `alembic/env.py`

Es fehlen ~8 Models (TopologyChangeLog, CachedContainerImage, AgentExecutionEvent, SkillBinding, etc.). Migrationen werden für diese Tabellen nicht generiert.

**Fix:** Alle Models in `alembic/env.py` und `models/sql/__init__.py` importieren:

```python
from app.models.sql.topology_models import TopologyChangeLog
from app.models.sql.artifact_schema_models import ArtifactSchema
from app.models.sql.analysis_models import AnalysisFinding
from app.models.sql.improvement_models import ImprovementAttempt
from app.models.sql.ab_test_models import ABTest, ABTestSample
from app.models.sql.shared_memory_models import Fact, Hypothesis, Relation
from app.models.sql.skill_build_models import SkillBinding, SkillBuildAttempt, PackageMapping, ResearchCache
from app.models.sql.cached_container_models import CachedContainerImage
```

---

### 4. TopologyLoader optional aber benötigt

**Datei:** `generic_executor.py`

TopologyLoader ist optional, aber `_get_agent_skills()` braucht ihn. Ohne ihn verlieren Agents still alle Skills.

**Fix:** TopologyLoader als required parameter, oder informativen Fehler werfen.

---

### 5. SkillBinding wird geflusht aber nicht committed

**Datei:** `capability_builder.py:701-757`

`db.flush()` statt `db.commit()`. Bindings existieren nur in der Transaction und gehen verloren.

**Fix:** Explizites Commit nach Binding-Erstellung.

---

### 6. Frontend ruft nicht-existierende Endpoints auf

**Dateien:** `frontend/src/lib/api.ts`, `frontend/src/app/execution/[id]/page.tsx`

- `/challenges/by-execution/{id}` - wird gepollt aber existiert nicht im Backend-Router
- `/challenges/analyze` vs Backend `/challenges/submit` - Naming-Mismatch
- `/telemetry/summary` - nicht in den Backend-Endpoints

**Fix:** Frontend-API-Client mit Backend-Router abgleichen.

---

## HOCH - Logik-Fehler die zu falschem Verhalten führen

### 7. Capability-Typ defaulted zu KNOWLEDGE

**Datei:** `challenge_analyzer.py:187-200`

Wenn das LLM den Typ vergisst, wird alles als KNOWLEDGE klassifiziert. Execution-Capabilities umgehen dann den FeasibilityJudge und werden als CAN_DO markiert, scheitern aber zur Runtime.

**Fix:** Default zu EXECUTION ändern (sicherer, da FeasibilityJudge dann prüft).

---

### 8. Confidence-Boost zu aggressiv

**Datei:** `gap_detector.py:182`

Ein Score von 0.5 kann auf 1.0 geboostet werden. "Ähnliches schon gemacht" sollte nicht "definitiv bereit" bedeuten.

**Fix:** Cap boost auf `min(base + boost, base * 1.3)` oder ähnlich.

---

### 9. SSE + Polling-Konflikt im Frontend

**Datei:** `execution/[id]/page.tsx`

Nutzt SSE UND pollt jede Sekunde. Race conditions, UI-Flicker, doppelte State-Updates.

**Fix:** Polling entfernen, nur SSE verwenden. Polling nur als Fallback wenn SSE nicht verbindet.

---

### 10. Keine LLM-Call-Timeouts

**Dateien:** `llm_client.py`, `generic_executor.py`

Wenn ein LLM-Call hängt, blockiert die gesamte Orchestration. Kein `asyncio.wait_for()`.

**Fix:** `asyncio.wait_for(llm_call, timeout=60)` um alle LLM-Calls.

---

### 11. Artifact-Validation scheitert still

**Datei:** `generic_executor.py:585-606`

ValueError wird gefangen und geloggt, aber Downstream-Agents bekommen ihre Inputs nicht.

**Fix:** Error propagieren oder Fallback-Artifact mit Fehlermeldung erstellen.

---

## MITTEL - Sollte gefixt werden für stabile Tests

### 12. DB-Transaktionen nicht atomar

**Datei:** `gap_plan_executor.py:136-142`

Gap-Status wird auf BUILDING gesetzt, dann Build gestartet. Wenn Build crasht, bleibt Status stuck. Kein Rollback.

**Fix:** Transaction-Context-Manager nutzen oder idempotente Status-Updates.

---

### 13. SharedMemory Dual-Write Inkonsistenz

**Datei:** `shared_memory/service.py:64-112`

Facts werden in Qdrant UND PostgreSQL geschrieben - wenn eins fehlschlägt, inkonsistenter State.

**Fix:** Für Tests: nur PostgreSQL als Source of Truth, Qdrant optional.

---

### 14. Topology-Validation-Cache wird stale

**Datei:** `topology/loader.py`

Cached Validation wird bei Reload nicht aktualisiert. Ungültige Topologien werden nicht erkannt.

**Fix:** Validation bei jedem Reload neu berechnen.

---

### 15. Sprach-Mix im Frontend

**Dateien:** `build-plan-display.tsx`, `execution-timeline-graph.tsx`, `history/page.tsx`

Deutsch/Englisch gemischt ("Analyseergebnis", "Klicken zum Ein-/Ausklappen" neben englischem UI).

**Fix:** Sprache vereinheitlichen (entweder komplett Deutsch oder komplett Englisch).

---

### 16. Keine SSE-Reconnection

**Datei:** `frontend/src/hooks/useSSE.ts`

Wenn die SSE-Verbindung abbricht, kein automatischer Retry. UI zeigt still "Not connected".

**Fix:** Exponential-Backoff Reconnection-Logic im Hook.

---

### 17. Auto-erstellte Agents haben leere Schemas

**Datei:** `capability_builder.py:759-886`

Specialist Agents bekommen `{"type": "object"}` als IO-Schema. Keine Downstream-Validation möglich.

**Fix:** Schemas aus Skill-APIs generieren oder zumindest die affected_capability als Schema-Hinweis nutzen.

---

## Empfohlene Reihenfolge

| Prio | Issue | Was | Aufwand |
|------|-------|-----|---------|
| 1 | #6 | Frontend/Backend Endpoint-Alignment | Mittel |
| 2 | #1 | Robustes JSON-Parsing | Klein |
| 3 | #2 | Embedding-Function sicherstellen | Klein |
| 4 | #3 | Alembic Model-Imports | Klein |
| 5 | #4 | TopologyLoader required machen | Klein |
| 6 | #5 | DB Commits fixen | Klein |
| 7 | #7 | Capability-Typ Default | Klein |
| 8 | #10 | LLM-Timeouts | Klein |
| 9 | #9 | SSE/Polling konsolidieren | Mittel |
| 10 | #11, #12 | Error-Handling in Orchestration | Mittel |
| 11 | #13, #14 | SharedMemory & Topology-Cache | Klein |
| 12 | #15, #16 | Frontend-Polish (Sprache, SSE-Reconnect) | Klein |
| 13 | #8, #17 | Confidence-Boost & Agent-Schemas | Klein |

---

## Architektonische Stärken

Das System hat viele gute Design-Entscheidungen:

- **Type-aware Capability Classification** (KNOWLEDGE vs EXECUTION)
- **Feasibility Verification** vor Gap-Closure
- **Fixed Gap Plans** (verhindert dass LLM jedes Mal neue Gaps "entdeckt")
- **Retry-Strategien mit Approach-Variation** (direct → simplified → fallback)
- **Lazy Loading** von Heavy Dependencies
- **Generic Agent Executor** (vollständig datengetrieben, kein Hardcoding)
- **Tool-Calling Loop** mit Max-Limits (verhindert Endlosschleifen)
- **Graceful Degradation** (Agents können fehlende Inputs überspringen)
- **Wave-basierte parallele Execution** mit sequentieller Wave-Abfolge
- **Shared Memory** für Cross-Run-Learning
