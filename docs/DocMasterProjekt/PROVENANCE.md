# PROVENANCE — Datenherkunft & Metrik-Korrektur (AP-1 + AP-12)

> **Zweck:** Nachweis, dass die berichteten Ergebnisse aus den korrekten Rohdaten stammen, und Dokumentation der Metrik-Vereinheitlichung (AP-1) + des RQ2-Bau-Pooling-Fixes (AP-12). Alle Zahlen sind aus den **bereits vorhandenen** Rohdaten neu gerechnet — **kein System-Neulauf**.

**Datenquelle:** `backend/results/thesis/` (dieselben Seed-JSONs, die `statistics.json` und die Plots in `docs/results/` erzeugt haben).
**Reproduzieren:** `cd backend && ../.venv/bin/python -m scripts.evaluation.reanalyze_metrics --results-dir results/thesis` → schreibt `backend/results/thesis/analysis/reanalysis.json`.
**Stand:** Juli 2026. Geprüft per Code-Review-Subagent (alle Kopf-Zahlen reproduzieren 1:1).

---

## 1. Reproduzierbarkeit & Archiv-Check
- ✅ **Kein Archiv-Leck:** `statistics.json` ist vollständig aus `backend/results/thesis/` reproduzierbar. Alle kanonischen Runs stammen vom **26.–29. Mai 2026**; `results_archive/` (April–22. Mai) fließt **nicht** ein.
- ✅ **7/9 Configs reproduzieren exakt** (per-Lauf-Erfolgsrate = `statistics.json`). Die zwei Abweichungen (Domain-Transfer) sind kein Datenfehler, sondern die Metrik-Definition (s. §2).
- Geladen: 32 Runs, Configs = ABL-STRONG-EVO-OFF(3), ABL-WEAK-EVO-OFF(3), ABL-WEAK-EVO-ON(3), CW-WEAK-WARM(3), DT-WEAK-COLD(3), DT-WEAK-WARM(3), U-MEDIUM-L3L5(3), U-STRONG-L3L5(3), U-WEAK-FULL(6), (l5_db cold/warm je 1 — nicht in den RQ-Zahlen).

## 2. Metrik-Definition (AP-1)
**Festgelegt:** *Erfolgsrate = Anteil der Läufe (Seed × Task) mit `score ≥ 0.85`* (per-Lauf-Aggregation, einheitlich für RQ1/RQ2/RQ3).
- **0.85 ist begründet:** systemeigene PASS-Schwelle (`verification_completeness_threshold = 0.85`), auch im laufenden Verify-Adapt-Loop.
- **Begriff:** „Pass@1" → **„Erfolgsrate (Score ≥ 0.85)"** umbenennen (Pass@1 stammt aus der Code-Generierung, irreführend).
- **Bisheriges Problem:** RQ1 nutzte eine *andere Aggregation* (erst pro Task über Seeds mitteln, nur L3–L5) als RQ2 (per Lauf). Gleiche Schwelle, verschiedene Aggregation → nicht vergleichbar.

## 3. Alt vs. korrigiert (die Kopf-Zahlen)

| Kennzahl | Alt (berichtet) | Korrigiert (einheitlich) | Konsequenz |
|---|---|---|---|
| **RQ1 Weak ON/OFF** | 61,9 % / 33,3 % (Δ **+28,6 pp**) — per-Task | 77,8 % / 57,1 % (Δ **+20,6 pp**) — per-Lauf | Effekt bleibt signifikant (Wilcoxon p=0.0225), Delta kleiner |
| **RQ1 Strong ON/OFF** | 71,4 % / 47,6 % (Δ **+23,8 pp**) — per-Task | 82,5 % / 69,8 % (Δ **+12,7 pp**) — per-Lauf | Effekt bleibt signifikant (p=0.0264), Delta deutlich kleiner |
| **RQ2-Bau Cold→Warm Tokens** | 2.216.825 → 2.176.679 (**−1,8 %**) — gepoolt | 1.927.486 → 2.176.679 (**+12,9 %**) — kampagnen-sauber | **Vorzeichen dreht:** Warm ist *teurer*, nicht billiger |
| **RQ2-Transfer Erfolg (τ=0.85)** | 25,0 % → 31,9 % | 25,0 % → 31,9 % (identisch) | Zahl stimmt, aber **schwellenabhängig** (s. §5) |

*(Die Wilcoxon-Signifikanz und Effektstärken bleiben unverändert — sie basieren auf den per-Task-Score-Differenzen, nicht auf der Erfolgsraten-Aggregation.)*

## 4. RQ2-Bau Pooling-Fix (AP-12)
`U-WEAK-FULL` (der Cold-Baseline) bestand aus **6 Seeds aus zwei Messkampagnen** (26. Mai `modellvergleich/` + 28. Mai `cold_warm/cold`). Die berichteten „−1,8 %" entstehen nur durch den teureren 26.-Mai-Lauf im Pool.

**Kampagnen-sauber (nur 28. Mai, je 3 Seeds):**
- Tokens: Cold **1.927.486** → Warm **2.176.679** = **+12,9 %** (Warm teurer)
- Erfolgsrate: **0,766 → 0,820** (+5,4 pp)
- **Ehrliche Aussage:** In der eingespielten Bau-Domäne *kostet* der Warm-Start mehr Tokens, *kauft* dafür aber etwas Qualität. Reuse spart hier **nicht**.

→ RQ2-Bau muss `cold_warm/cold` vs `cold_warm/warm` verwenden; der 6-Seed-Pool `U-WEAK-FULL` nur für den Modell-Tier-Vergleich (Friedman).

## 5. Schwellen-Sensitivität (der wichtige neue Befund)
**RQ2-Transfer — der „Gewinn" ist schwellenabhängig:**

| τ | Cold | Warm | Effekt |
|---|---|---|---|
| 0.70 | 70,8 % | 69,4 % | **Warm schlechter** ⚠ |
| 0.80 | 54,2 % | 55,6 % | Warm minimal besser |
| 0.85 | 25,0 % | 31,9 % | Warm besser (berichtet) |

Der Durchschnitts-Score ist **praktisch flach** (0,6423 → 0,6384, minimal niedriger). Die berichtete Verbesserung ist also ein reiner **Schwellen-Übersprung-Effekt** und **dreht sich bei τ=0.70 um**. → In der Arbeit **mit Sensitivität berichten**, nicht als robuste Verbesserung verkaufen.

**RQ2-Bau — konsistent über alle Schwellen:** Warm besser bei Erfolg (τ=0.85: 0,766→0,820; τ=0.70: 0,775→0,829), aber teurer — der Qualitäts-für-Tokens-Trade-off ist robust.

## 6. Was das für die Arbeit heißt
- **RQ1:** Ergebnis **hält** (signifikant, positiv) — aber die Schlagzeilen-Deltas schrumpfen (Weak +20,6 statt +28,6; Strong +12,7 statt +23,8). Einheitliche per-Lauf-Zahlen verwenden.
- **RQ2:** **ehrlicher und differenzierter** als bisher — in der Bau-Domäne spart Reuse *nicht* (kostet sogar mehr), im Transfer spart es Tokens (−16,2 %, robust), aber die Qualitäts-„Verbesserung" ist schwellenfragil.
- **RQ3:** von dieser Korrektur nicht betroffen.

## 7. Zu aktualisieren (nach Freigabe)
- `Results.md` — RQ1-Tabelle (Deltas), RQ2-Bau-Abschnitt (−1,8 % → +12,9 % / „spart nicht"), RQ2-Transfer mit Sensitivität + Metrik-Definition.
- `docs/DocMasterProjekt/README.md` — Judge-Passus „absichtlich vom ausführenden Modell entkoppelt" korrigieren (im Strong-Tier war Modell = Judge = `gemini-3.5-flash`).
- **Plots in `docs/results/`** neu erzeugen, sobald Zahlen final: `rq1_evolution_effect.png`, `rq1_evolution_by_level.png`, `rq2_cold_warm_tokens.png` (die von den korrigierten Zahlen abhängen).
- Thesis Kap. 6.3 (Metrik-Definition + τ-Sensitivität), 6.5 (RQ2-Bau korrigiert), 7.4 (Judge=System-Modell, Judge- vs. deterministische Bewertung).

## 8. Verifizierte Quellen
- `backend/scripts/evaluation/model_comparison.py` — `PASS_THRESHOLD = 0.85`; `compute_pass_at_1` (per Lauf); `evolution_ablation` (per Task gemittelt, L3–L5, aligned).
- `backend/scripts/evaluation/benchmark_runner.py` — `CLAIM_PASS_THRESHOLD = 0.85`; `evaluate_claims` (LLM-Judge, „toleranter Evaluator"); `evaluate_pass` (strikt, Keyword/Section).
- `backend/results/thesis/analysis/statistics.json` — Referenz für „alt".
- `backend/results/thesis/analysis/reanalysis.json` — Ausgabe dieser Re-Analyse (Rohzahlen aller Blöcke).
- `docs/DocMasterProjekt/METRIK_FIX.md` — die zugrunde liegende Problem-Erklärung.
