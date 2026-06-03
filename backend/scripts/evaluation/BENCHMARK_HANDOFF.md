# Benchmark Handoff — Thesis Evaluation

## Situation

Alle Benchmark-Infrastruktur ist fertig. Die vollständige Thesis-Evaluation muss jetzt durchgeführt werden.

## Was existiert

- **Master-Script**: `backend/scripts/evaluation/run_full_evaluation.sh` — orchestriert alle 5 Phasen
- **8 Model-Configs** in `backend/scripts/evaluation/model_configs/`:
  - `u_weak_full.yaml` (gemini-2.0-flash, L1-L5)
  - `u_medium_l3l5.yaml` (gemini-2.5-flash, L3-L5)
  - `u_strong_l3l5.yaml` (gemini-3.5-flash, L3-L5)
  - `abl_weak_evo_on.yaml` (2.0-flash, L3-L5, Evolution ON)
  - `abl_weak_evo_off.yaml` (2.0-flash, L3-L5, Evolution OFF)
  - `abl_strong_evo_off.yaml` (3.5-flash, L3-L5, Evolution OFF)
  - `cw_weak_warm.yaml` (2.0-flash, L1-L5, warm mode für RQ2)
  - `dt_weak_cold.yaml` (2.0-flash, domain_transfer Suite)
- **Gatekeeper-Evaluator**: `backend/scripts/evaluation/gatekeeper_evaluator.py` — bereits getestet, 100% Accuracy
- **Analyse-Pipeline**: `backend/scripts/evaluation/model_comparison.py` + `plot_comparison.py`
- **Results-Ordner**: `backend/results/thesis/` (leer, bereit)
- **Archiv**: Alte Ergebnisse in `backend/results_archive/`

## Was VOR dem Start geprüft werden muss

1. **Modell-Verfügbarkeit**: `gemini-2.5-flash` und `gemini-3.5-flash` testen (kurzer API-Call)
2. **Backend läuft**: `curl http://localhost:8000/api/v1/dashboard/health`
3. **Docker läuft**: Für Sandbox-Execution (Skill-Building)
4. **Cold-Reset funktioniert**: `python3 -m scripts.evaluation.cold_warm_switch cold`
5. **.env korrekt**: `LLM_MODEL=gemini/gemini-2.0-flash` (nicht das tote gemini-3.1-flash-lite-preview)

## Durchführung

```bash
cd backend

# Dry-Run zuerst:
bash scripts/evaluation/run_full_evaluation.sh --dry-run

# Dann phasenweise starten (empfohlen, da ~28h Gesamtlaufzeit):

# Phase 1: Modellvergleich (~11h)
bash scripts/evaluation/run_full_evaluation.sh --phase 1

# Phase 2: Ablation (~8h)
bash scripts/evaluation/run_full_evaluation.sh --phase 2

# Phase 3: Cold/Warm (~5h)
bash scripts/evaluation/run_full_evaluation.sh --phase 3

# Phase 4: Domain Transfer (~3h)
bash scripts/evaluation/run_full_evaluation.sh --phase 4

# Phase 5: Gatekeeper (<1min, bereits getestet)
bash scripts/evaluation/run_full_evaluation.sh --phase 5
```

## Monitoring

Jeden laufenden Benchmark per Log verfolgen:
```bash
# Log-Datei anlegen und monitoren:
bash scripts/evaluation/run_full_evaluation.sh --phase 1 2>&1 | tee results/thesis/phase1.log
```

Oder per API:
```bash
curl -s http://localhost:8000/api/v1/dashboard/recent | python3 -m json.tool
```

## Nach Abschluss aller Phasen

```bash
# Analyse-Pipeline starten:
python3 -m scripts.evaluation.model_comparison \
  --results results/thesis/ \
  --output results/thesis/analysis/

python3 -m scripts.evaluation.plot_comparison \
  --results results/thesis/ \
  --output results/thesis/plots/
```

## Bekannte Issues

- **L3_warranty_claim_report**: Scheitert konsistent mit build_failed (~38s). Kein Modell-Problem — systematischer Build-Fehler bei diesem Task. Erwartet in den Ergebnissen.
- **L3+ Tasks**: Können 5-12 Minuten dauern (Build + Execute). Timeouts bei 1800s.
- **Cold-Reset zwischen Seeds**: Wird automatisch vom Runner gemacht bei mode=cold.
- **Phase 3 (Cold/Warm)**: Gepaarte Seeds — nach jedem Cold-Run folgt ein Warm-Run auf demselben State. KEIN Reset zwischen Cold und Warm innerhalb eines Seed-Paars.

## Run-Matrix Übersicht

| Phase | RQ | Config | Suite | Levels | Seeds | ~Dauer |
|-------|-----|--------|-------|--------|-------|--------|
| 1 | RQ1 | u_weak_full | progressive_complexity | L1-L5 | 3 | 3h |
| 1 | RQ1 | u_medium_l3l5 | progressive_complexity | L3-L5 | 3 | 4h |
| 1 | RQ1 | u_strong_l3l5 | progressive_complexity | L3-L5 | 3 | 4h |
| 2 | RQ1 | abl_weak_evo_on | progressive_complexity | L3-L5 | 3 | 2h |
| 2 | RQ1 | abl_weak_evo_off | progressive_complexity | L3-L5 | 3 | 2h |
| 2 | RQ1 | abl_strong_evo_off | progressive_complexity | L3-L5 | 3 | 4h |
| 3 | RQ2 | u_weak_full → cw_weak_warm | progressive_complexity | L1-L5 | 3×2 | 5h |
| 4 | Gen. | dt_weak_cold | domain_transfer | L1-L4 | 3 | 3h |
| 5 | RQ3 | (gatekeeper_evaluator) | gatekeeper_skills | — | — | <1min |
