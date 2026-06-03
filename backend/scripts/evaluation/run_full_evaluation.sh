#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# LUMARI THESIS EVALUATION — Master Run Script
# ═══════════════════════════════════════════════════════════════
#
# Fuehrt alle Benchmarks fuer die Masterarbeit durch:
#   Phase 1: Modellvergleich (RQ1)        — 3 Configs × 3 Seeds
#   Phase 2: Evolution-Ablation (RQ1)     — 3 Configs × 3 Seeds
#   Phase 3: Cold/Warm-Vergleich (RQ2)    — 3 gepaarte Cold→Warm Seeds
#   Phase 4: Domain Transfer              — 1 Config × 3 Seeds
#   Phase 5: Gatekeeper (RQ3)             — 40 Skills
#
# Gesamtdauer: ~28h sequentiell, ~$30 API-Kosten
#
# Usage:
#   cd backend
#   bash scripts/evaluation/run_full_evaluation.sh [--phase N] [--dry-run]
#
# Optionen:
#   --phase N    Nur Phase N ausfuehren (1-5)
#   --dry-run    Nur anzeigen was laufen wuerde
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

RUNNER="python3 -m scripts.evaluation.benchmark_runner"
COLD="python3 -m scripts.evaluation.cold_warm_switch cold"
GATEKEEPER="python3 -m scripts.evaluation.gatekeeper_evaluator"
DIR="results/thesis"
PHASE_FILTER="all"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) PHASE_FILTER="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        *) shift ;;
    esac
done

mkdir -p "$DIR"/{modellvergleich,ablation,cold_warm,domain_transfer,gatekeeper}

log() { echo ""; echo "$(date +%H:%M:%S) [$1] $2"; }
run() {
    if $DRY_RUN; then echo "  [DRY] $*"; else eval "$@"; fi
}

echo "═══════════════════════════════════════════════════════════"
echo " LUMARI THESIS EVALUATION — $(date)"
echo " Output: $DIR/"
echo "═══════════════════════════════════════════════════════════"

# ─── Phase 1: Modellvergleich (RQ1) ──────────────────────────
if [[ "$PHASE_FILTER" == "all" || "$PHASE_FILTER" == "1" ]]; then
    log "PHASE 1" "Modellvergleich — 3 Tiers × 3 Seeds"

    log "1/3" "U-WEAK-FULL (gemini-2.0-flash, L1-L5, 37 Tasks)"
    run $COLD
    run $RUNNER --suite progressive_complexity \
        --model-config u_weak_full --seeds 3 --mode cold \
        --output "$DIR/modellvergleich/u_weak_full.json"

    log "2/3" "U-MEDIUM-L3L5 (gemini-2.5-flash, L3-L5, 21 Tasks)"
    run $COLD
    run $RUNNER --suite progressive_complexity \
        --model-config u_medium_l3l5 --seeds 3 --mode cold \
        --output "$DIR/modellvergleich/u_medium_l3l5.json"

    log "3/3" "U-STRONG-L3L5 (gemini-3.5-flash, L3-L5, 21 Tasks)"
    run $COLD
    run $RUNNER --suite progressive_complexity \
        --model-config u_strong_l3l5 --seeds 3 --mode cold \
        --output "$DIR/modellvergleich/u_strong_l3l5.json"

    log "PHASE 1" "FERTIG"
fi

# ─── Phase 2: Evolution-Ablation (RQ1) ───────────────────────
if [[ "$PHASE_FILTER" == "all" || "$PHASE_FILTER" == "2" ]]; then
    log "PHASE 2" "Evolution-Ablation — 2×2 Factorial"

    log "1/3" "ABL-WEAK-EVO-ON (gemini-2.0-flash, L3-L5, Evolution ON)"
    run $COLD
    run $RUNNER --suite progressive_complexity \
        --model-config abl_weak_evo_on --seeds 3 --mode cold \
        --output "$DIR/ablation/abl_weak_evo_on.json"

    log "2/3" "ABL-WEAK-EVO-OFF (gemini-2.0-flash, L3-L5, Evolution OFF)"
    run $COLD
    run $RUNNER --suite progressive_complexity \
        --model-config abl_weak_evo_off --seeds 3 --mode cold \
        --output "$DIR/ablation/abl_weak_evo_off.json"

    log "3/3" "ABL-STRONG-EVO-OFF (gemini-3.5-flash, L3-L5, Evolution OFF)"
    run $COLD
    run $RUNNER --suite progressive_complexity \
        --model-config abl_strong_evo_off --seeds 3 --mode cold \
        --output "$DIR/ablation/abl_strong_evo_off.json"

    # ABL-STRONG-EVO-ON = U-STRONG-L3L5 (identisch, kein Extra-Run)

    log "PHASE 2" "FERTIG"
fi

# ─── Phase 3: Cold/Warm-Vergleich (RQ2) ──────────────────────
# Gepaarte Seeds: Cold→Warm auf identischem State, dann Reset
if [[ "$PHASE_FILTER" == "all" || "$PHASE_FILTER" == "3" ]]; then
    log "PHASE 3" "Cold/Warm-Vergleich — 3 gepaarte Seeds"

    for seed in 1 2 3; do
        log "SEED $seed" "Cold-Run (L1-L5, 37 Tasks)"
        run $COLD
        run $RUNNER --suite progressive_complexity \
            --model-config u_weak_full --seeds 1 --mode cold \
            --seed "$seed" \
            --output "$DIR/cold_warm/cold_seed${seed}.json"

        log "SEED $seed" "Warm-Run (gleicher State, L1-L5)"
        run $RUNNER --suite progressive_complexity \
            --model-config cw_weak_warm --seeds 1 --mode warm \
            --seed "$seed" \
            --output "$DIR/cold_warm/warm_seed${seed}.json"
    done

    log "PHASE 3" "FERTIG"
fi

# ─── Phase 4: Domain Transfer ────────────────────────────────
if [[ "$PHASE_FILTER" == "all" || "$PHASE_FILTER" == "4" ]]; then
    log "PHASE 4" "Domain Transfer — IT + Meeting-Protokolle (24 Tasks)"

    run $COLD
    run $RUNNER --suite domain_transfer \
        --model-config dt_weak_cold --seeds 3 --mode cold \
        --output "$DIR/domain_transfer/dt_weak_cold.json"

    log "PHASE 4" "FERTIG"
fi

# ─── Phase 5: Gatekeeper (RQ3) ───────────────────────────────
if [[ "$PHASE_FILTER" == "all" || "$PHASE_FILTER" == "5" ]]; then
    log "PHASE 5" "Gatekeeper — 40 Skills (20 safe + 20 unsafe)"

    run $GATEKEEPER --output "$DIR/gatekeeper/gatekeeper_results.json"

    log "PHASE 5" "FERTIG"
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo " EVALUATION ABGESCHLOSSEN — $(date)"
echo " Ergebnisse in: $DIR/"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Naechster Schritt: Analyse-Pipeline"
echo "  python3 -m scripts.evaluation.model_comparison --results $DIR/ --output $DIR/analysis/"
