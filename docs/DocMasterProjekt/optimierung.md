# Optimierungspotenziale — Token-Effizienz (RQ2)

## Problem

Blueprint-Reuse eliminiert die Build-Phase (−100%), aber der Gesamttoken-Verbrauch sinkt nicht.
In der eingespielten Bau-Domäne ist der Warm-Run **nicht günstiger** — kampagnen-sauber verglichen (dieselbe Messreihe, je 3 Seeds, 28. Mai) verbraucht er brutto sogar **+12,9 % mehr Tokens** (1,93 Mio. → 2,18 Mio.), kauft dafür aber etwas Qualität (Erfolgsrate 76,6 % → 82,0 %). Ein Teil dieses Aufschlags kann Retry-Overhead sein (Warm-Runs laufen zeitlich später, s. Brutto/Netto-Trennung unten). *(Eine frühere Angabe von ~1,8 % beruhte auf einem Pooling zweier Messkampagnen unterschiedlicher Tage — Artefakt; siehe [`PROVENANCE.md`](PROVENANCE.md).)*

## Ursachenanalyse

### Token-Verteilung pro Task (Warm-Run)

| Phase | Tokens | Lernbar? |
|---|---|---|
| Pre-Execution (Analyzer + GapDetector + FeasibilityJudge) | ~15–20k | Ja — bei bekanntem Task-Typ überflüssig |
| TeamAssembler (LLM-Call) | ~5–10k | Ja — Team ist schon bekannt |
| Wave-Execution (Agents generieren Bericht) | ~20–40k | Teilweise — weniger Waves möglich |
| Verification | ~5–10k | Nein — Qualitätssicherung muss bleiben |
| **Gesamt** | **~50–80k** | |

### Warum Blueprint-Reuse allein nicht reicht

1. **Build-Tokens sind klein** — Skill-Pipeline ~10–20k Tokens/Skill, aber Task-Execution dominiert (~40–50k/Task)
2. **Execution-Kosten sind fix** — das LLM muss Inhalt generieren, egal ob Skill neu oder reused
3. **Prompt-Overhead wächst** — statische Skill-Zuordnung, nicht-zugewiesene Skills bei allen Agents (kein Task-basiertes Filtering)
4. **Orchestrierungs-Pipeline redundant** — Pre-Execution + TeamAssembler laufen jedes Mal voll, auch bei bekannten Task-Typen

### Bestehende Mechanismen und ihre Grenzen

- **TeamAssembler** stellt per LLM aufgabenspezifische Teams zusammen — aber plant *jedes Mal* neu
- **StrategyMemory** speichert Ergebnisse als Freitext-Facts in SharedMemory — aber nicht als wiederverwendbare Execution-Pläne
- **Wave-Berechnung** basiert auf Agent-Dependencies — lernt aber nicht "Tagesbericht braucht 1 Wave statt 3"
- Topologie hilft bei **Team-Auswahl**, aber nicht bei **Execution-Optimierung**

## Optimierungen (nach Impact gerankt)

### 1. Plan-Cache (höchster Impact: ~25–35% Token-Einsparung)

Wenn ein Task-Typ (z.B. "Tagesbericht") 3x mit Score >0.85 gelaufen ist:
- Pre-Execution **komplett skippen** → −15–20k Tokens
- TeamAssembler **komplett skippen** → −5–10k Tokens
- Nur Lightweight-Check: "Existieren die benötigten Skills noch?" (kein LLM-Call)
- Gelernte Wave-Anzahl direkt verwenden

**Implementierung (~1–2 Tage):**
1. Challenge-Type hashen (existiert bereits in `StrategyMemory._extract_challenge_type`)
2. Erfolgreiche TeamPlans als wiederverwendbare Pläne cachen (nicht nur Freitext)
3. Bei Match mit ausreichend Confidence → Pre-Execution + TeamAssembler skippen

**Effekt:** Erzeugt messbare Lernkurve — je öfter ein Task-Typ läuft, desto weniger Tokens. Genau das was RQ2 hypothesiert.

### 2. Template-Reuse (Impact: ~30–40% auf Execution-Tokens)

Berichtsstruktur aus erfolgreichen Runs extrahieren und wiederverwenden:
- System weiß: "Tagesbericht = 5 Abschnitte: Wetter, Personal, Fortschritt, Mängel, Nächste Schritte"
- LLM muss nur noch Fakten einsetzen statt Struktur + Inhalt zu generieren
- Weniger Output-Tokens, weniger Retries wegen falscher Struktur

**Einschränkung:** Hilft nur bei L1–L4 (Berichte), nicht bei L5 (Tool-Nutzung).

### 3. Task-basiertes Skill-Filtering (Impact: ~5–10% Token-Einsparung)

Per Embedding-Match nur relevante Skills pro Task laden:
- Aktuell: nicht-zugewiesene Skills bei allen Agents im Prompt
- Optimiert: Qdrant-Suche matcht Task-Description gegen Skill-Descriptions, nur Top-K laden
- Reduziert Prompt-Overhead bei wachsender Skill-Anzahl

**Implementierung:** Gering (~0.5–1 Tag), Embedding-Infrastruktur (Qdrant) existiert bereits.

## Sonderfall L5 (DB, Audio, APIs)

### Korrigierte Diagnose (Benchmark L5 DB, 2026-05-30)

Die frühere Annahme "Skills werden gebaut aber nicht als Tools aufgerufen" ist **widerlegt**. Nach den Skill-Build-Fixes (Test-Kontext-Extraktion, Infrastruktur-Guard, `test_input`-Durchreichung — siehe ALGORITHMUS.md §5) zeigt eine neue **Tool-Call-Metrik** im Benchmark-Runner, dass die Skills tatsächlich aufgerufen werden und überwiegend erfolgreich laufen:

| Lauf | Pass@1 | Tool-Call-Erfolgsrate | Unique Skills |
|---|---|---|---|
| Cold | 20% | 91% (32/35) | 8 |
| Warm | 0% | 100% (28/28) | 7 |

**Erkenntnis:** Der Flaschenhals ist **nicht** das Skill-Building, sondern LLM-Reasoning/Aggregation. Die Tools liefern korrekte Einzelergebnisse (91–100% Erfolg), aber das Modell setzt sie nicht zur richtigen Endantwort zusammen (Multi-Step-Workflow, Zwischenergebnisse interpretieren, mehrere Tool-Outputs aggregieren). Der Warm-Pass@1-Einbruch (20%→0%) trotz 100% Tool-Erfolg unterstreicht das: an den Skills liegt es nicht.

### Konsequenz für Optimierungen

- **Plan-Cache** hilft weiterhin (gelernte Workflows: "Für DB-Tasks: 1. db_connector → 2. Query → 3. Ergebnis formatieren"), entlastet aber primär die Orchestrierung, nicht das Reasoning.
- **Template-Reuse** hilft hier kaum (kein Report-Problem, sondern Workflow-/Aggregations-Problem).
- Der eigentliche Hebel für L5-Pass@1 liegt im **Reasoning/Aggregations-Schritt** (z.B. iteratives Reasoning, explizite Aggregations-Anweisungen, Reflexion über Tool-Outputs) — nicht in weiteren Skill-Build-Verbesserungen.

### Messung: Tool-Call-Metrik

`scripts/evaluation/benchmark_runner.py` zählt via `_extract_tool_call_metrics()` pro Task die Tool-Calls (total/succeeded/failed), berechnet die Erfolgsrate und trackt unique Skills — als Per-Task-Werte und als Aggregat im JSON/CSV-Output. `scripts/evaluation/plot_l5_db.py` rendert dazu zwei neue Plots (Skill-Qualität vs. Task-Erfolg, Tool-Calls pro Task). Diese Metrik trennt erstmals sauber "Skill funktioniert" von "Task gelöst".

## Messmethodik: Brutto/Netto-Token-Trennung

### Problem

DNS-Instabilität verursacht LLM-Retries, die den Token-Verbrauch aufblähen. Dieser Confounder ist unabhängig vom System (keine Eigenschaft der Self-Evolution) und betrifft Warm-Runs überproportional, weil sie zeitlich später laufen.

### Lösung: Zwei Metriken ausweisen

- **Brutto-Tokens**: Alles was tatsächlich verbraucht wurde (inkl. fehlgeschlagene Calls + Retries)
- **Netto-Tokens**: Nur erfolgreiche Calls (ohne Retry-Overhead)

Cold vs. Warm wird auf **beiden** Metriken verglichen. Keine Datenpunkte werden entfernt — beides wird transparent berichtet.

### Thesis-Formulierung

> "Die Brutto-Token-Messung zeigt keinen signifikanten Unterschied (p=0.22), da Netzwerk-Retries den Warm-Run überproportional betrafen. Nach Bereinigung um Retry-Overhead zeigt der Netto-Token-Verbrauch einen Rückgang von X% (p=Y)."

### Umsetzung

1. Prüfen ob LiteLLM Retries separat loggt (vermutlich ja via `litellm.callbacks`)
2. Falls nicht: eigenen Callback einbauen der erfolgreiche vs. fehlgeschlagene Calls zählt
3. Final-Run mit Brutto/Netto-Tracking, stabile Verbindung (kabelgebunden, nachts)

## Fazit

Blueprint-Reuse allein reicht nicht für messbare Gesamttoken-Reduktion — in der Bau-Domäne ist der Warm-Start aktuell sogar teurer (+12,9 % brutto). Die Orchestrierungs-Pipeline (Pre-Execution, Team-Planning) wird bei bekannten Task-Typen redundant wiederholt. Ein Plan-Cache würde ~25–35% Token-Einsparung bringen und könnte den Warm-Start-Effekt überhaupt erst in einen Netto-Gewinn drehen.

Kombination Plan-Cache + Template-Reuse könnte ~50% Gesamtersparnis erreichen — dann würde RQ2 auch bei n=3 statistisch signifikant werden.
