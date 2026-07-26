"""Re-Analyse der Erfolgsmetrik (AP-1) + RQ2-Bau-Pooling-Fix (AP-12).

Liest DIESELBEN Rohdaten wie model_comparison.py / statistics.json
(backend/results/thesis/, Seed-JSONs, gruppiert nach model_config_id) und
rechnet die Kopf-Zahlen mit EINER einheitlichen Definition neu.

=========================== DEFINIERTE GOALS ================================
G1  Datenquelle identisch zu statistics.json: rglob *.json unter --results-dir,
    "aggregate"/"analysis" überspringen, gruppieren nach model_config_id.
    Zusätzlich pro Datei das Quell-Unterverzeichnis behalten (für AP-12).
G2  EINHEITLICHE Metrik: Erfolgsrate = Anteil Läufe (Seed x Task) mit
    score >= tau, tau=0.85. Diese "per-Lauf"-Aggregation wird auf ALLE Configs
    angewandt -- inkl. RQ1-Ablation (die bisher per-Task-Mittel nutzt).
G3  Transparenz RQ1: beide Aggregationen ausgeben -- per-Lauf (neu/einheitlich)
    UND per-Task-Mittel (alt, wie evolution_ablation) -- plus Wilcoxon (auf
    per-Task-Mittelwerten, unveraendert) fuer die Signifikanz.
G4  Schwellen-Sensitivitaet: Erfolgsrate bei tau in {0.7, 0.8, 0.85} fuer die
    RQ1-Paare, RQ2-Transfer und RQ2-Bau.
G5  AP-12 RQ2-Bau: Cold/Warm BEIDE Wege -- (a) gepoolt U-WEAK-FULL (6 Seeds)
    vs CW-WEAK-WARM, (b) kampagnen-sauber cold_warm/cold vs cold_warm/warm
    (je 3 Seeds) -- fuer Tokens UND Erfolgsrate.
G6  "alt vs korrigiert": je Kopf-Zahl der aktuell berichtete Wert aus
    statistics.json vs der neu gerechnete Wert.
G7  Maschinenlesbarer JSON-Output + menschenlesbare Zusammenfassung (stdout),
    aus der die PROVENANCE.md gebaut werden kann.
G8  Read-only auf Rohdaten; schreibt NUR die Output-JSON.
G9  Deterministisch (keine RNG-Abhaengigkeit in den berichteten Kernzahlen).
=============================================================================
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import wilcoxon

TAUS = [0.70, 0.80, 0.85]
TAU_MAIN = 0.85

ABLATION_PAIRS = [
    ("ABL-WEAK-EVO-ON", "ABL-WEAK-EVO-OFF", "Weak"),
    ("U-STRONG-L3L5", "ABL-STRONG-EVO-OFF", "Strong"),
]
ABLATION_LEVELS = {"L3", "L4", "L5"}  # wie evolution_ablation() in model_comparison.py


# ---------------------------------------------------------------- Daten laden
def load_runs(results_dir: str) -> list[dict]:
    """G1: identische Ladelogik wie model_comparison.load_results_dir,
    aber mit Quell-Unterverzeichnis + Dateiname pro Run (fuer AP-12)."""
    root = Path(results_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"Verzeichnis nicht gefunden: {root}")
    runs = []
    for jf in sorted(root.rglob("*.json")):
        if "aggregate" in jf.name or "analysis" in jf.name:
            continue
        try:
            data = json.load(open(jf))
        except Exception:
            continue
        if not (isinstance(data, dict) and isinstance(data.get("tasks"), list)):
            continue
        runs.append({
            "config_id": data.get("model_config_id") or re.sub(r"_seed\d+$", "", jf.stem),
            "subdir": jf.parent.name,
            "stem": jf.stem,
            "seed": data.get("seed"),
            "started_at": str(data.get("started_at") or "")[:10],
            "judge_model": data.get("judge_model"),
            "model": (data.get("models_used") or {}).get("general") if isinstance(data.get("models_used"), dict) else None,
            "tasks": data["tasks"],
        })
    return runs


def by_config(runs: list[dict]) -> dict[str, list[dict]]:
    g = defaultdict(list)
    for r in runs:
        g[r["config_id"]].append(r)
    return dict(g)


# ------------------------------------------------------------- Metrik-Helfer
def _scores(run_list: list[dict], levels: set[str] | None = None) -> list[float]:
    out = []
    for r in run_list:
        for t in r["tasks"]:
            if levels and t.get("level") not in levels:
                continue
            out.append(float(t.get("score") or 0.0))
    return out


def success_per_obs(run_list: list[dict], tau: float, levels=None) -> float:
    """G2: Anteil einzelner Laeufe (Seed x Task) mit score >= tau."""
    s = _scores(run_list, levels)
    return sum(1 for x in s if x >= tau) / len(s) if s else 0.0


def _task_means(run_list: list[dict], levels: set[str] | None = None) -> dict[str, float]:
    per_task = defaultdict(list)
    for r in run_list:
        for t in r["tasks"]:
            if levels and t.get("level") not in levels:
                continue
            per_task[t["task_id"]].append(float(t.get("score") or 0.0))
    return {tid: float(np.mean(v)) for tid, v in per_task.items()}


def success_per_task_mean(run_list: list[dict], tau: float, levels=None) -> float:
    """G3: erst pro Task ueber Seeds mitteln, dann Schwelle (wie evolution_ablation)."""
    m = _task_means(run_list, levels)
    return sum(1 for x in m.values() if x >= tau) / len(m) if m else 0.0


def mean_score(run_list: list[dict], levels=None) -> float:
    s = _scores(run_list, levels)
    return float(np.mean(s)) if s else 0.0


def tokens_per_run(run_list: list[dict]) -> float:
    per = [sum(int(t.get("tokens_total") or 0) for t in r["tasks"]) for r in run_list]
    return float(np.mean(per)) if per else 0.0


def n_obs(run_list, levels=None) -> int:
    return len(_scores(run_list, levels))


# -------------------------------------------------------------- Analyse-Bloecke
def rq1_ablation(cfg: dict[str, list[dict]]) -> list[dict]:
    """G3: beide Aggregationen + Wilcoxon auf per-Task-Mitteln, aligned wie im Original."""
    out = []
    for on_id, off_id, tier in ABLATION_PAIRS:
        if on_id not in cfg or off_id not in cfg:
            out.append({"tier": tier, "error": f"{on_id} oder {off_id} fehlt"})
            continue
        on, off = cfg[on_id], cfg[off_id]
        # aligned tasks (Schnittmenge, wie _align_subset in model_comparison)
        m_on = _task_means(on, ABLATION_LEVELS)
        m_off = _task_means(off, ABLATION_LEVELS)
        common = sorted(set(m_on) & set(m_off))
        arr_on = np.array([m_on[t] for t in common])
        arr_off = np.array([m_off[t] for t in common])
        try:
            stat, p = wilcoxon(arr_on, arr_off, zero_method="wilcox")
        except ValueError:
            stat, p = float("nan"), 1.0
        row = {
            "tier": tier, "pair": [on_id, off_id], "n_tasks_aligned": len(common),
            "wilcoxon_p": round(float(p), 6), "significant": bool(p < 0.05),
            # NEU/einheitlich: per-Lauf, ALLE Level
            "success_per_obs": {
                "on": round(success_per_obs(on, TAU_MAIN), 4),
                "off": round(success_per_obs(off, TAU_MAIN), 4),
            },
            "n_obs": {"on": n_obs(on), "off": n_obs(off)},
            # ALT: per-Task-Mittel, nur L3-L5 (wie evolution_ablation)
            "success_per_task_mean_L3L5": {
                "on": round(success_per_task_mean(on, TAU_MAIN, ABLATION_LEVELS), 4),
                "off": round(success_per_task_mean(off, TAU_MAIN, ABLATION_LEVELS), 4),
            },
            "mean_score": {"on": round(mean_score(on), 4), "off": round(mean_score(off), 4)},
        }
        row["delta_pp_per_obs"] = round((row["success_per_obs"]["on"] - row["success_per_obs"]["off"]) * 100, 1)
        row["delta_pp_per_task_mean"] = round((row["success_per_task_mean_L3L5"]["on"] - row["success_per_task_mean_L3L5"]["off"]) * 100, 1)
        # G4 Sensitivitaet (per-Lauf)
        row["sensitivity_per_obs"] = {
            f"tau_{tau}": {"on": round(success_per_obs(on, tau), 4), "off": round(success_per_obs(off, tau), 4)}
            for tau in TAUS
        }
        out.append(row)
    return out


def rq2_bau(runs: list[dict], cfg: dict[str, list[dict]]) -> dict:
    """G5 (AP-12): gepoolt vs kampagnen-sauber."""
    warm = cfg.get("CW-WEAK-WARM", [])
    pooled_cold = cfg.get("U-WEAK-FULL", [])           # 6 Seeds (2 Kampagnen)
    clean_cold = [r for r in runs if r["subdir"] == "cold_warm" and "cold" in r["stem"]]  # 3 Seeds, 28. Mai

    def block(cold, warm, label):
        ct, wt = tokens_per_run(cold), tokens_per_run(warm)
        return {
            "label": label,
            "cold_seeds": len(cold), "warm_seeds": len(warm),
            "cold_dates": sorted({r["started_at"] for r in cold}),
            "warm_dates": sorted({r["started_at"] for r in warm}),
            "tokens_cold": round(ct), "tokens_warm": round(wt),
            "delta_tokens_pct": round((wt - ct) / ct * 100, 1) if ct else None,
            "success_cold": round(success_per_obs(cold, TAU_MAIN), 4),
            "success_warm": round(success_per_obs(warm, TAU_MAIN), 4),
            "mean_score_cold": round(mean_score(cold), 4),
            "mean_score_warm": round(mean_score(warm), 4),
            # G4: Schwellen-Sensitivitaet auch fuer RQ2-Bau
            "sensitivity": {f"tau_{tau}": {"cold": round(success_per_obs(cold, tau), 4),
                                           "warm": round(success_per_obs(warm, tau), 4)} for tau in TAUS},
        }

    return {
        "pooled_current": block(pooled_cold, warm, "GEPOOLT (U-WEAK-FULL, 6 Seeds, 2 Kampagnen) -- aktuell berichtet"),
        "campaign_clean": block(clean_cold, warm, "KAMPAGNEN-SAUBER (cold_warm/cold, 3 Seeds, 28. Mai)"),
    }


def rq2_transfer(cfg: dict[str, list[dict]]) -> dict:
    cold, warm = cfg.get("DT-WEAK-COLD", []), cfg.get("DT-WEAK-WARM", [])
    res = {
        "tokens_cold": round(tokens_per_run(cold)), "tokens_warm": round(tokens_per_run(warm)),
        "delta_tokens_pct": round((tokens_per_run(warm) - tokens_per_run(cold)) / tokens_per_run(cold) * 100, 1) if cold else None,
        "mean_score_cold": round(mean_score(cold), 4), "mean_score_warm": round(mean_score(warm), 4),
        "success_per_obs": {f"tau_{tau}": {"cold": round(success_per_obs(cold, tau), 4),
                                           "warm": round(success_per_obs(warm, tau), 4)} for tau in TAUS},
    }
    return res


def old_vs_corrected(stats: dict, rq1: list[dict], bau: dict, transfer: dict) -> list[dict]:
    """G6: aktuell berichtete Werte (aus statistics.json) vs neu gerechnet."""
    rows = []
    ea = {r["tier"]: r for r in stats.get("evolution_ablation", []) if "tier" in r}
    for r in rq1:
        if "error" in r:
            continue
        tier = r["tier"]
        old = ea.get(tier, {})
        rows.append({
            "kennzahl": f"RQ1 {tier} Erfolgsrate ON/OFF",
            "alt (statistics.json, per-Task-Mittel)": f"{old.get('pass_at_1_on')}/{old.get('pass_at_1_off')} (Δ {round((old.get('pass_at_1_on',0)-old.get('pass_at_1_off',0))*100,1)}pp)",
            "korrigiert (per-Lauf, alle Level)": f"{r['success_per_obs']['on']}/{r['success_per_obs']['off']} (Δ {r['delta_pp_per_obs']}pp)",
        })
    p1 = stats.get("pass_at_1", {})
    # G6: "alt" echt aus statistics.json lesen (nicht neu rechnen)
    old_cold = p1.get("U-WEAK-FULL", {}).get("tokens_mean")
    old_warm = p1.get("CW-WEAK-WARM", {}).get("tokens_mean")
    old_delta = round((old_warm - old_cold) / old_cold * 100, 1) if old_cold else None
    rows.append({
        "kennzahl": "RQ2-Bau Cold→Warm Tokens",
        "alt (statistics.json, gepoolt)": f"{old_cold:,}→{old_warm:,} ({old_delta}%)" if old_cold else "n/a",
        "korrigiert (kampagnen-sauber)": f"{bau['campaign_clean']['tokens_cold']:,}→{bau['campaign_clean']['tokens_warm']:,} ({bau['campaign_clean']['delta_tokens_pct']}%)",
    })
    rows.append({
        "kennzahl": "RQ2-Transfer Erfolgsrate Cold→Warm (τ=0.85)",
        "alt (statistics.json)": f"{p1.get('DT-WEAK-COLD',{}).get('pass_at_1')}→{p1.get('DT-WEAK-WARM',{}).get('pass_at_1')}",
        "korrigiert (per-Lauf, identisch)": f"{transfer['success_per_obs']['tau_0.85']['cold']}→{transfer['success_per_obs']['tau_0.85']['warm']}",
        "hinweis": f"mean_score {transfer['mean_score_cold']}→{transfer['mean_score_warm']} (praktisch flach → schwellenabhaengig)",
    })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", default="results/thesis")
    ap.add_argument("--stats", default="results/thesis/analysis/statistics.json")
    ap.add_argument("--out", default="results/thesis/analysis/reanalysis.json")
    args = ap.parse_args()

    runs = load_runs(args.results_dir)
    cfg = by_config(runs)
    stats = json.load(open(args.stats)) if Path(args.stats).is_file() else {}

    rq1 = rq1_ablation(cfg)
    bau = rq2_bau(runs, cfg)
    transfer = rq2_transfer(cfg)
    comparison = old_vs_corrected(stats, rq1, bau, transfer)

    report = {
        "meta": {
            "results_dir": args.results_dir, "tau_main": TAU_MAIN, "taus": TAUS,
            "definition": "Erfolgsrate = Anteil Laeufe (Seed x Task) mit score >= tau (per-Lauf).",
            "n_runs_loaded": len(runs),
            "configs": {str(c): len(v) for c, v in sorted(cfg.items(), key=lambda kv: str(kv[0]))},
        },
        "rq1_ablation": rq1,
        "rq2_bau_ap12": bau,
        "rq2_transfer": transfer,
        "old_vs_corrected": comparison,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    json.dump(report, open(out, "w"), indent=2, ensure_ascii=False)

    # ---- menschenlesbare Zusammenfassung ----
    print(f"\n=== Re-Analyse (tau={TAU_MAIN}) — {len(runs)} Runs, {len(cfg)} Configs ===\n")
    print("RQ1 — Evolutions-Ablation:")
    for r in rq1:
        if "error" in r:
            print(f"  {r['tier']}: {r['error']}"); continue
        print(f"  {r['tier']:6s} per-Lauf ON/OFF = {r['success_per_obs']['on']:.3f}/{r['success_per_obs']['off']:.3f} (Δ{r['delta_pp_per_obs']:+.1f}pp) "
              f"| alt per-Task = {r['success_per_task_mean_L3L5']['on']:.3f}/{r['success_per_task_mean_L3L5']['off']:.3f} (Δ{r['delta_pp_per_task_mean']:+.1f}pp) "
              f"| Wilcoxon p={r['wilcoxon_p']:.4f}")
    print("\nRQ2-Bau (AP-12):")
    for k in ("pooled_current", "campaign_clean"):
        b = bau[k]
        print(f"  {b['label']}")
        print(f"      Cold {b['tokens_cold']:,} ({b['cold_seeds']} Seeds {b['cold_dates']}) → Warm {b['tokens_warm']:,} = {b['delta_tokens_pct']:+.1f}% | Erfolg {b['success_cold']:.3f}→{b['success_warm']:.3f}")
    print("\nRQ2-Transfer:")
    t = transfer
    print(f"  Tokens {t['tokens_cold']:,}→{t['tokens_warm']:,} ({t['delta_tokens_pct']:+.1f}%) | mean_score {t['mean_score_cold']:.3f}→{t['mean_score_warm']:.3f}")
    for tau in TAUS:
        s = t["success_per_obs"][f"tau_{tau}"]
        print(f"      Erfolg τ={tau}: {s['cold']:.3f}→{s['warm']:.3f}")
    print(f"\n→ JSON: {out}")


if __name__ == "__main__":
    main()
