# Phase 0 — Diagnose-Bericht

**Datum:** 2026-04-30
**Bezug:** Plan `lovely-purring-tiger.md`
**Quellen:** `sprint_ab_cold_20260429_121049.{json,log}`, `run_20260429_163621.{json,log}`

---

## 0.1 — Build-Timeout-Forensik

### Symptom
3 von 60 Tasks (5%) brechen mit `status="build_timeout"`, `agents_executed=0`,
`tokens_total=0` ab. Die Tasks haben Phase 1 (ANALYZE) erfolgreich
durchlaufen, aber Phase 2 (BUILD) erreicht nie `status=ready`.

| Task | Run | Phase 1 ANALYZE | Phase 2 BUILD |
|------|-----|-----------------|---------------|
| L1_simple_daily_report | sprint_ab_cold | 2974ms (route=developer_team) | timeout 180s |
| L1_defect_list | sprint_ab_cold | 2019ms (route=developer_team) | timeout 180s |
| L4_energy_evaluation | run_163621 | 4374ms (route=developer_team) | timeout 180s |

Zum Vergleich: Erfolgreiche developer_team-Builds (z.B. `L1_safety_protocol`,
`L4_procurement_documentation`) brauchen **~20s** in Phase 2. Die Timeouts
sind also 9× langsamer als der Median, nicht "viele Skills sequenziell",
sondern echter Hänger.

### Root Cause

**Es gibt KEIN internes Timeout im Build-Pfad.** Das beobachtete 180s ist
ausschließlich Runner-seitig (`benchmark_runner.py:341`,
`build_timeout = timeout * 0.6`). Backend-seitig läuft die Capability-Building
ohne Zeitlimit weiter — auch nachdem der Runner aufgegeben hat.

**Code-Pfad ohne Timeout-Wrapper:**

| Schicht | Datei:Zeile | Timeout? |
|---------|-------------|----------|
| API-Endpoint triggert BG-Task | `app/api/v1/endpoints/challenges.py:1352` (`background_tasks.add_task`) | ❌ keiner |
| Background-Task | `app/api/v1/endpoints/challenges.py:1424` (`orchestrator.process_blocked_challenge`) | ❌ keiner |
| Intervention-Plan-Execution | `app/orchestration/intervention/orchestrator.py:177` (`plan_executor.execute_plan`) | ❌ keiner |
| SkillTeamOrchestrator (5-Rollen-Pipeline) | `app/services/skill_team_orchestrator.py` | ❌ keiner |
| LLM-Calls innerhalb der Rollen | überall | abhängig von litellm-Defaults |

**Hypothese welche Phase hängt:** Eine der LLM-Calls in der
Researcher → Architect → Implementer → Reviewer → Tester Kette wartet auf
eine Antwort, die nicht kommt. Verdächtig:
1. `gemini-3.1-flash-lite-preview` Provider-seitiger Hänger (kein
   Client-Timeout gesetzt)
2. Sandbox-Phase im Tester (apt/pip Installation hängt)
3. Embedding-Service Timeout (Qdrant-Insert nach Skill-Build)

**Backend-Server-Logs werden NICHT persistiert** (`start.sh:153` — uvicorn
nur stdout, keine Datei). Forensik-Limit. Ohne Backend-Log-Capture können
wir die genaue Stelle nicht ohne Re-Run identifizieren.

### Konsequenzen

1. **Wasted Backend-Work**: Nach Runner-Timeout läuft der Build-Task im
   Backend weiter, blockiert evtl. Worker für den nächsten Task. Erklärt
   möglicherweise sekundäre Verlangsamung in den Folge-Tasks.
2. **Kein build_failed-Status**: Der polling-Loop des Runners sieht ewig
   `status=building`, daher kein graceful Failure. Der nächste Task startet
   unter Umständen mit halb-fertigem State.
3. **Verfälscht Pass@1**: 3 Hard-Fails à 0.0 Score drücken die
   Erfolgsrate um ~5pp.

### Fix-Vektor (Phase 1, separater Plan)

- **Innerer Timeout** in `_run_capability_building`
  (`challenges.py:1378`): `await asyncio.wait_for(orchestrator.process_blocked_challenge(...),
  timeout=settings.build_total_timeout)` mit z.B. 240s. Bei TimeoutError →
  `status=build_failed` setzen.
- **Backend-Log-Capture** in `start.sh:153`:
  `uvicorn ... 2>&1 | tee logs/backend_$(date +%Y%m%d_%H%M%S).log`. Ohne
  Logs ist jede künftige Diagnose blind.
- **Optional: pro-Rolle LLM-Timeout** (z.B. 60s) im SkillTeamOrchestrator,
  damit hängende API-Calls die ganze Pipeline nicht stoppen.

---

## 0.2 — Token-Profiling-Instrumentierung

### Erledigt
- `generic_executor.py:815-835` — additives Logging ergänzt.
  Loggt pro Agent-Execution `facts_kept`, `facts_total`, `hypotheses`,
  `relations`, `approx_tokens`, `query_chars`.
- Verhalten unverändert; kein Risiko.
- Beobachtung: Code zeigt bereits sauberes Sprint-A/B-Gating
  (`{shared_memory}`-Template-Check in Z. 792, `max_items=8`,
  `top_k=5`). **Memory-Cap ist bereits korrekt** — frühere Annahme
  "qdrant limit=50" war falsch, der Caller überschreibt das.

### Verbleibende Token-Sink-Hypothesen (zu validieren in 0.3)
1. **Hypothesen-Such-Limit** ist hardcoded `limit=20` in
   `shared_memory/service.py:307` — möglicherweise größter Kostenblock.
2. **Anzahl Agents mit `{shared_memory}`-Platzhalter** unbekannt — wenn
   viele Agents Memory ziehen, multipliziert sich der Per-Agent-Cap.
3. **Relations-Block** (`service.py:316`, `fact_ids[:10]`) — pro Fact bis
   zu N Relations.

---

## 0.3 — Single-Task-Reproduktion (erledigt 2026-04-30)

**Run:** `validation_l3_20260430_115402` — `L3_acceptance_protocol`
(zuvor Faktenrecall-Failure-Profil, viele Zahlen/DIN-Codes/Geldbeträge).

**Ergebnis nach Fixes (Faktenrecall-Constraint + Build-Timeout):**

| Metrik | Wert | Vorher (sprint_ab_cold) |
|--------|------|--------------------------|
| `pass` | True | False |
| `score` | 1.0 | <0.5 |
| `agents_executed` | 11 | — |
| `tokens_total` | 56198 | — |
| `duration_ms` | 75684 | timeout/fail |

**Memory-Profil aus Backend-Log (`backend_20260430_114949.log`):**

```
shared_memory_metrics agent=transcript_analyzer facts_kept=5 facts_total=8
  hypotheses=0 relations=0 approx_tokens=2583 query_chars=6555
```

**Befunde:**
- Nur 1 von 11 Agents hat `{shared_memory}`-Platzhalter — Sprint B.2-Gating
  greift wie erwartet (Entry-Point-Only).
- `top_k=5` filtert 8 → 5 Facts, korrekt.
- `hypotheses=0` und `relations=0` → Hypothesen-Cap-Fix (#5) **NICHT
  nötig**, kein Token-Sink an dieser Stelle.
- `approx_tokens=2583` für den Memory-Block sind unbedenklich gegenüber
  den 56198 Total-Tokens des Runs (~4.6%).
- Faktenrecall-Constraint im System-Prompt wirkt: Output enthält alle
  8 required_claims wörtlich (DIN 18195, 1,0%, 4.800 EUR, 56 dB usw.).

**Aussage zur Hypothese:** Memory-Token-Profil ist sauber, weiteres Tuning
am Hypothesen-Limit nicht prioritär. Die 60%-Pass@1-Stagnation der
2026-04-29-Runs war primär ein Faktenrecall-Problem, kein Memory-Problem.



**User-Aufgabe:** Backend neu starten (Logging-Edit lädt automatisch via
`--reload`), einen L3/L4-Task ausführen, Backend-Log nach
`shared_memory_metrics`-Zeilen filtern.

```bash
# Backend muss laufen
grep "shared_memory_metrics" /tmp/backend.log
```

**Erwartete Datenpunkte pro Agent:**
- `facts_kept` (sollte ≤ 5 sein wegen `top_k`)
- `hypotheses` (vermutete Token-Sink, falls > 0)
- `approx_tokens` (Summe-Schätzung)

Ohne diese Daten ist jede weitere Token-Optimierung Spekulation.

---

## 0.4 — Priorisierte Folgemaßnahmen

| # | Maßnahme | Datei | Aufwand | Erwarteter Effekt |
|---|----------|-------|---------|-------------------|
| 1 | Innerer Timeout im Capability-Building | `challenges.py:1378-1466` | S | 0 Build-Timeouts mit `agents_executed=0`. Sauberes `build_failed` statt 180s-Hang. |
| 2 | Backend-Log-Capture in start.sh | `start.sh:153` | XS | Künftige Diagnosen möglich. Sollte SOFORT geschehen. |
| 3 | Faktenrecall-Constraint im Executor-Prompt | `generic_executor.py:_call_llm` System-Prompt | S | L3/L4 Score-Steigerung, Zahlen/Codes/Namen werden wörtlich übernommen. |
| 4 | Multi-Seed Benchmark-Runner | `scripts/evaluation/benchmark_runner.py` | M | Statistisch belastbare RQ1-Aussage (Wilcoxon p-Wert). |
| 5 | Hypothesen-Cap konfigurierbar | `service.py:307` + `config.py` | XS | Nur falls 0.3 zeigt dass Hypothesen >15% des Memory-Budgets ausmachen. |

### Nächster Schritt (Empfehlung)

Bevor weitere Fixes: **#2 (Log-Capture) und 0.3 (Single-Task-Run) ausführen**.
Erst danach mit Daten im Rücken den V2-Plan schreiben.

Wenn Kapazität für nur einen Code-Fix vorhanden: **#1 (innerer Timeout)** —
das ist der größte Korrektheits-Gewinn pro Aufwand-Einheit und macht
zukünftige Cold-Runs reproduzierbar.

### Out of Scope für Phase 0 / V2

- Ablation Study (RQ-Ergebnisse hängen erst von #1 + #4 ab)
- Gatekeeper Test (RQ3, separater Pfad)
- Domain Transfer (letzter Schritt)