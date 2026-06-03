from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import friedmanchisquare, wilcoxon

ALPHA = 0.05
PASS_THRESHOLD = 0.85

FRIEDMAN_CONFIGS = {
    "T-Weak": "ABL-WEAK-EVO-ON",
    "T-Medium": "U-MEDIUM-L3L5",
    "T-Strong": "U-STRONG-L3L5",
}

ABLATION_PAIRS = [
    ("ABL-WEAK-EVO-ON", "ABL-WEAK-EVO-OFF", "Weak"),
    ("U-STRONG-L3L5", "ABL-STRONG-EVO-OFF", "Strong"),
]


def load_results_dir(results_dir: str) -> dict[str, list[dict]]:
    """Lädt alle Seed-JSONs aus einem Verzeichnis, gruppiert nach Config-ID."""
    path = Path(results_dir)
    if not path.is_dir():
        raise FileNotFoundError(f"Verzeichnis nicht gefunden: {path}")

    configs: dict[str, list[dict]] = defaultdict(list)

    for json_file in sorted(path.rglob("*.json")):
        if "aggregate" in json_file.name or "analysis" in json_file.name:
            continue
        with open(json_file) as f:
            data = json.load(f)
        config_id = data.get("model_config_id") or _infer_config_id(json_file.stem)
        if "tasks" in data:
            configs[config_id].append(data)

    return dict(configs)


def _infer_config_id(stem: str) -> str:
    return re.sub(r"_seed\d+$", "", stem)


def align_tasks(
    configs: dict[str, list[dict]],
    levels: set[str] | None = None,
    require_all: bool = True,
) -> dict[str, dict]:
    """Aligned Tasks über Configs.

    Returns:
        {task_id: {config_id: [score_seed1, ...], "level": "L3"}}
    """
    all_task_ids: set[str] = set()
    for runs in configs.values():
        for run in runs:
            for t in run.get("tasks", []):
                if levels is None or t["level"] in levels:
                    all_task_ids.add(t["task_id"])

    aligned: dict[str, dict] = {}
    config_ids = set(configs.keys())

    for tid in sorted(all_task_ids):
        entry: dict[str, Any] = {}
        for config_id, runs in configs.items():
            scores = []
            for run in runs:
                task = next((t for t in run.get("tasks", []) if t["task_id"] == tid), None)
                if task:
                    entry["level"] = task["level"]
                    scores.append(task.get("score", 0.0))
            if scores:
                entry[config_id] = scores

        if require_all:
            if config_ids <= set(entry.keys()) - {"level"}:
                aligned[tid] = entry
        else:
            aligned[tid] = entry

    return aligned


def _align_subset(
    configs: dict[str, list[dict]],
    subset_ids: list[str],
    levels: set[str] | None = None,
) -> dict[str, dict]:
    """Aligned Tasks nur für bestimmte Config-IDs."""
    subset = {cid: configs[cid] for cid in subset_ids if cid in configs}
    return align_tasks(subset, levels, require_all=True)


def bootstrap_ci(
    data: np.ndarray,
    n_boot: int = 10000,
    ci: float = 0.95,
) -> tuple[float, float]:
    """Bootstrap-Konfidenzintervall für den Mittelwert."""
    rng = np.random.default_rng(42)
    means = np.array([
        np.mean(rng.choice(data, size=len(data), replace=True))
        for _ in range(n_boot)
    ])
    alpha = (1 - ci) / 2
    return (
        round(float(np.percentile(means, alpha * 100)), 4),
        round(float(np.percentile(means, (1 - alpha) * 100)), 4),
    )


def compute_pass_at_1(configs: dict[str, list[dict]], levels: set[str] | None = None) -> dict[str, dict]:
    """Berechnet Pass@1 pro Config, pro Level, und gesamt."""
    results: dict[str, dict] = {}

    for config_id, runs in configs.items():
        per_level: dict[str, list[float]] = defaultdict(list)
        all_scores: list[float] = []
        cost_per_seed: list[float] = []
        tokens_per_seed: list[int] = []

        for run in runs:
            seed_cost = run.get("cost_usd_total", 0.0)
            cost_per_seed.append(seed_cost)
            seed_tokens = 0

            for t in run.get("tasks", []):
                if levels and t["level"] not in levels:
                    continue
                per_level[t["level"]].append(t.get("score", 0.0))
                all_scores.append(t.get("score", 0.0))
                seed_tokens += t.get("tokens_total", 0) or 0
            tokens_per_seed.append(seed_tokens)

        total_pass = sum(1 for s in all_scores if s >= PASS_THRESHOLD)
        total_count = len(all_scores)

        level_stats = {}
        for lv, scores in sorted(per_level.items()):
            lv_pass = sum(1 for s in scores if s >= PASS_THRESHOLD)
            level_stats[lv] = {
                "pass_at_1": round(lv_pass / len(scores), 4) if scores else 0.0,
                "n_tasks": len(scores),
                "mean_score": round(float(np.mean(scores)), 4),
            }

        scores_arr = np.array(all_scores) if all_scores else np.array([0.0])
        ci = bootstrap_ci(scores_arr)

        results[config_id] = {
            "pass_at_1": round(total_pass / total_count, 4) if total_count else 0.0,
            "n_observations": total_count,
            "n_seeds": len(runs),
            "mean_score": round(float(np.mean(scores_arr)), 4),
            "std_score": round(float(np.std(scores_arr)), 4),
            "ci_95": list(ci),
            "per_level": level_stats,
            "cost_per_seed": cost_per_seed,
            "cost_mean": round(float(np.mean(cost_per_seed)), 4) if cost_per_seed else 0.0,
            "tokens_per_seed": tokens_per_seed,
            "tokens_mean": int(np.mean(tokens_per_seed)) if tokens_per_seed else 0,
            "model": _get_primary_model(runs[0]) if runs else None,
        }

    return results


def _get_primary_model(run: dict) -> str | None:
    models = run.get("models_used")
    if not models:
        return None
    return Counter(models.values()).most_common(1)[0][0]


def rank_biserial(x: list[float], y: list[float]) -> float:
    """Rank-biserial Correlation als Effekt-Größe für Wilcoxon."""
    diffs = [a - b for a, b in zip(x, y)]
    nonzero = [d for d in diffs if d != 0]
    if not nonzero:
        return 0.0
    ranked = sorted(enumerate(nonzero), key=lambda t: abs(t[1]))
    pos_sum = neg_sum = 0.0
    for rank, (_, v) in enumerate(ranked, start=1):
        if v > 0:
            pos_sum += rank
        else:
            neg_sum += rank
    total = pos_sum + neg_sum
    return (pos_sum - neg_sum) / total if total else 0.0


def capability_friedman(
    configs: dict[str, list[dict]],
    levels: set[str] = {"L3", "L4", "L5"},
) -> dict:
    """Friedman-Test über die 3 Tiers (Plan-konforme Datenquellen).

    Verwendet FRIEDMAN_CONFIGS: T-Weak=ABL-WEAK-EVO-ON, T-Medium=U-MEDIUM-L3L5,
    T-Strong=U-STRONG-L3L5 — alle starten cold bei L3 ohne L1/L2-Vorlauf.
    """
    tier_labels = list(FRIEDMAN_CONFIGS.keys())
    tier_config_ids = list(FRIEDMAN_CONFIGS.values())

    missing = [cid for cid in tier_config_ids if cid not in configs]
    if missing:
        return {"test": "friedman_capability", "error": f"Configs fehlen: {missing}"}

    aligned = _align_subset(configs, tier_config_ids, levels)
    if len(aligned) < 3:
        return {
            "test": "friedman_capability",
            "error": f"Nur {len(aligned)} gemeinsame Tasks nach Alignment",
        }

    task_ids = sorted(aligned.keys())
    arrays = {}
    for label, cid in FRIEDMAN_CONFIGS.items():
        arrays[label] = [float(np.mean(aligned[t][cid])) for t in task_ids]

    try:
        stat, p_value = friedmanchisquare(*arrays.values())
    except Exception as e:
        return {"test": "friedman_capability", "error": str(e)}

    result: dict[str, Any] = {
        "test": "friedman_capability",
        "tiers": {label: cid for label, cid in FRIEDMAN_CONFIGS.items()},
        "n_tasks": len(task_ids),
        "task_ids": task_ids,
        "statistic": round(float(stat), 4),
        "p_value": round(float(p_value), 6),
        "significant": bool(p_value < ALPHA),
        "means": {t: round(float(np.mean(a)), 4) for t, a in arrays.items()},
        "medians": {t: round(float(np.median(a)), 4) for t, a in arrays.items()},
    }

    if p_value < ALPHA:
        n_comp = len(list(combinations(tier_labels, 2)))
        posthoc = []
        for t1, t2 in combinations(tier_labels, 2):
            a1, a2 = arrays[t1], arrays[t2]
            try:
                w_stat, w_p = wilcoxon(a1, a2, zero_method="wilcox")
                rb = rank_biserial(a1, a2)
            except ValueError as e:
                posthoc.append({"comparison": f"{t1} vs {t2}", "error": str(e)})
                continue

            p_corr = min(w_p * n_comp, 1.0)
            posthoc.append({
                "comparison": f"{t1} vs {t2}",
                "W": round(float(w_stat), 4),
                "p_value": round(float(w_p), 6),
                "p_bonferroni": round(float(p_corr), 6),
                "significant": p_corr < ALPHA,
                "rank_biserial": round(rb, 4),
                "direction": f"{t1} > {t2}" if rb > 0 else f"{t2} > {t1}",
            })
        result["posthoc"] = posthoc
        result["bonferroni_alpha"] = round(ALPHA / n_comp, 6)

    return result


def friedman_test(aligned: dict[str, dict], config_ids: list[str]) -> dict:
    """Generischer Friedman-Test über beliebige Configs (≥3 Gruppen, gepaart)."""
    groups: dict[str, list[float]] = {cid: [] for cid in config_ids}

    for tid, entry in sorted(aligned.items()):
        for cid in config_ids:
            scores = entry.get(cid, [])
            groups[cid].append(float(np.mean(scores)) if scores else 0.0)

    arrays = [groups[cid] for cid in config_ids]
    n_tasks = len(arrays[0])

    if n_tasks < 3:
        return {"test": "friedman", "error": f"Zu wenig Tasks ({n_tasks})"}

    try:
        stat, p_value = friedmanchisquare(*arrays)
    except Exception as e:
        return {"test": "friedman", "error": str(e)}

    return {
        "test": "friedman",
        "statistic": round(float(stat), 4),
        "p_value": round(float(p_value), 6),
        "n_tasks": n_tasks,
        "k_groups": len(config_ids),
        "significant": bool(p_value < ALPHA),
        "config_ids": config_ids,
    }


def posthoc_wilcoxon(
    aligned: dict[str, dict],
    config_ids: list[str],
    alpha: float = ALPHA,
) -> list[dict]:
    """Paarweise Wilcoxon post-hoc mit Bonferroni-Korrektur."""
    pairs = list(combinations(config_ids, 2))
    n_comparisons = len(pairs)
    bonferroni_alpha = alpha / n_comparisons if n_comparisons else alpha

    results = []
    for cid_a, cid_b in pairs:
        means_a, means_b = [], []
        for tid, entry in sorted(aligned.items()):
            sa = entry.get(cid_a, [])
            sb = entry.get(cid_b, [])
            means_a.append(float(np.mean(sa)) if sa else 0.0)
            means_b.append(float(np.mean(sb)) if sb else 0.0)

        diffs = [a - b for a, b in zip(means_a, means_b)]
        nonzero = [d for d in diffs if d != 0]

        if not nonzero:
            results.append({
                "pair": [cid_a, cid_b],
                "statistic": 0.0, "p_value": 1.0,
                "p_value_corrected": 1.0, "significant": False,
                "effect_size": 0.0,
            })
            continue

        try:
            stat, p_val = wilcoxon(means_a, means_b, zero_method="wilcox")
        except ValueError:
            stat, p_val = float("nan"), 1.0

        p_corrected = min(p_val * n_comparisons, 1.0)
        effect = rank_biserial(means_a, means_b)

        results.append({
            "pair": [cid_a, cid_b],
            "statistic": round(float(stat), 4) if not math.isnan(stat) else None,
            "p_value": round(float(p_val), 6),
            "p_value_corrected": round(float(p_corrected), 6),
            "significant": p_corrected < alpha,
            "effect_size": round(effect, 4),
            "bonferroni_alpha": round(bonferroni_alpha, 6),
        })

    return results


def evolution_ablation(
    configs: dict[str, list[dict]],
    levels: set[str] = {"L3", "L4", "L5"},
) -> list[dict]:
    """Wilcoxon-Tests für Evolution ON vs OFF (Plan: 2×2 Ablation)."""
    results = []

    for evo_on_id, evo_off_id, tier_label in ABLATION_PAIRS:
        if evo_on_id not in configs or evo_off_id not in configs:
            results.append({"tier": tier_label, "error": f"{evo_on_id} oder {evo_off_id} fehlt"})
            continue

        aligned = _align_subset(configs, [evo_on_id, evo_off_id], levels)
        if len(aligned) < 3:
            results.append({"tier": tier_label, "error": f"Nur {len(aligned)} gepaarte Tasks"})
            continue

        task_ids = sorted(aligned.keys())
        means_on = [float(np.mean(aligned[t][evo_on_id])) for t in task_ids]
        means_off = [float(np.mean(aligned[t][evo_off_id])) for t in task_ids]

        nonzero = [a - b for a, b in zip(means_on, means_off) if a != b]
        if not nonzero:
            results.append({
                "tier": tier_label, "pair": [evo_on_id, evo_off_id],
                "n_tasks": len(task_ids), "statistic": 0.0,
                "p_value": 1.0, "significant": False,
                "effect_size": 0.0, "delta_pass_at_1": 0.0,
            })
            continue

        try:
            stat, p_val = wilcoxon(means_on, means_off, zero_method="wilcox")
        except ValueError:
            stat, p_val = float("nan"), 1.0

        effect = rank_biserial(means_on, means_off)
        on_arr = np.array(means_on)
        off_arr = np.array(means_off)
        p1_on = float(np.mean(on_arr >= PASS_THRESHOLD))
        p1_off = float(np.mean(off_arr >= PASS_THRESHOLD))

        results.append({
            "tier": tier_label,
            "pair": [evo_on_id, evo_off_id],
            "n_tasks": len(task_ids),
            "statistic": round(float(stat), 4) if not math.isnan(stat) else None,
            "p_value": round(float(p_val), 6),
            "significant": p_val < ALPHA,
            "effect_size": round(effect, 4),
            "mean_score_on": round(float(np.mean(on_arr)), 4),
            "mean_score_off": round(float(np.mean(off_arr)), 4),
            "ci_95_on": list(bootstrap_ci(on_arr)),
            "ci_95_off": list(bootstrap_ci(off_arr)),
            "pass_at_1_on": round(p1_on, 4),
            "pass_at_1_off": round(p1_off, 4),
            "delta_pass_at_1": round(p1_on - p1_off, 4),
            "effect_direction": "Evolution hilft" if effect > 0 else "Evolution schadet",
        })

    return results


def token_analysis(
    configs: dict[str, list[dict]],
    levels: set[str] = {"L3", "L4", "L5"},
) -> dict[str, Any]:
    """H4: Verbrauchen Thinking-Modelle überproportional mehr Tokens?"""
    tier_tokens: dict[str, dict[str, dict]] = {}

    for tier_label, config_id in FRIEDMAN_CONFIGS.items():
        if config_id not in configs:
            continue

        per_task: dict[str, list[dict]] = {}
        for run in configs[config_id]:
            for task in run["tasks"]:
                if task["level"] not in levels:
                    continue
                tid = task["task_id"]
                per_task.setdefault(tid, []).append({
                    "tokens_total": task.get("tokens_total", 0),
                    "tokens_input": task.get("tokens_input", 0),
                    "tokens_output": task.get("tokens_output", 0),
                    "tokens_thinking": task.get("tokens_thinking", 0),
                })

        aggregated = {}
        for tid, measurements in per_task.items():
            total = float(np.mean([m["tokens_total"] for m in measurements]))
            thinking = float(np.mean([m["tokens_thinking"] for m in measurements]))
            output = float(np.mean([m["tokens_output"] for m in measurements]))
            aggregated[tid] = {
                "tokens_total_mean": total,
                "tokens_thinking_mean": thinking,
                "thinking_ratio": thinking / max(output, 1),
            }
        tier_tokens[tier_label] = aggregated

    common = sorted(set.intersection(*(set(td.keys()) for td in tier_tokens.values()))) if tier_tokens else []
    tiers = list(tier_tokens.keys())

    result: dict[str, Any] = {"tiers": tiers, "n_tasks": len(common)}

    if len(common) >= 3 and len(tiers) >= 3:
        arrays = {
            tier: np.array([tier_tokens[tier][t]["tokens_total_mean"] for t in common])
            for tier in tiers
        }
        stat, p_value = friedmanchisquare(*arrays.values())
        result["friedman_tokens"] = {
            "statistic": round(float(stat), 4),
            "p_value": round(float(p_value), 6),
            "significant": bool(p_value < ALPHA),
        }
        result["mean_tokens"] = {t: int(np.mean(a)) for t, a in arrays.items()}
        result["median_tokens"] = {t: int(np.median(a)) for t, a in arrays.items()}

    thinking_ratios = {}
    for tier, tasks in tier_tokens.items():
        ratios = [t["thinking_ratio"] for t in tasks.values()]
        thinking_ratios[tier] = round(float(np.mean(ratios)), 4) if ratios else 0.0
    result["thinking_token_ratio"] = thinking_ratios

    return result


def quality_cost_analysis(pass_at_1: dict[str, dict]) -> dict[str, Any]:
    """Quality/Cost Ratio, Pareto-Frontier, Break-even."""
    configs_data = {}
    for config_id, stats in pass_at_1.items():
        cost = stats.get("cost_mean", 0.0)
        p1 = stats.get("pass_at_1", 0.0)
        ratio = round(p1 / cost, 2) if cost > 0 else float("inf")
        configs_data[config_id] = {
            "pass_at_1": p1,
            "cost_mean": cost,
            "quality_cost_ratio": ratio,
            "model": stats.get("model"),
        }

    items = list(configs_data.items())
    for cid, a in items:
        dominated = False
        for other_cid, b in items:
            if other_cid == cid:
                continue
            if b["pass_at_1"] >= a["pass_at_1"] and b["cost_mean"] <= a["cost_mean"]:
                if b["pass_at_1"] > a["pass_at_1"] or b["cost_mean"] < a["cost_mean"]:
                    dominated = True
                    break
        a["pareto_optimal"] = not dominated

    sorted_by_cost = sorted(configs_data.items(), key=lambda x: x[1]["cost_mean"])
    break_even = []
    for i in range(len(sorted_by_cost) - 1):
        cheap_id, cheap = sorted_by_cost[i]
        expensive_id, expensive = sorted_by_cost[i + 1]
        delta_cost = expensive["cost_mean"] - cheap["cost_mean"]
        delta_quality = expensive["pass_at_1"] - cheap["pass_at_1"]
        if delta_quality > 0 and delta_cost > 0:
            cost_per_quality_point = delta_cost / delta_quality
            break_even.append({
                "from": cheap_id,
                "to": expensive_id,
                "delta_cost_per_run": round(delta_cost, 4),
                "delta_pass_at_1": round(delta_quality, 4),
                "cost_per_quality_point": round(cost_per_quality_point, 4),
            })

    return {
        "configs": configs_data,
        "pareto_frontier": [cid for cid, d in configs_data.items() if d["pareto_optimal"]],
        "break_even": break_even,
    }


def _build_task_score_matrix(
    configs: dict[str, list[dict]],
    levels: set[str] | None = None,
) -> dict[str, dict]:
    """Baut eine Task×Config Matrix mit Mean-Scores für die Heatmap.

    Returns: {task_id: {"level": "L3", config_id: mean_score, ...}}
    """
    aligned = align_tasks(configs, levels, require_all=False)
    matrix = {}
    for tid, entry in aligned.items():
        row = {"level": entry.get("level", "?")}
        for key, val in entry.items():
            if key == "level":
                continue
            if isinstance(val, list):
                row[key] = round(float(np.mean(val)), 3)
        matrix[tid] = row
    return matrix


def build_report(
    configs: dict[str, list[dict]],
    levels: set[str] | None = None,
) -> dict:
    """Erstellt den vollständigen Analyse-Report."""
    pass_at_1 = compute_pass_at_1(configs, levels)
    config_ids = sorted(configs.keys())

    report: dict[str, Any] = {
        "n_configs": len(config_ids),
        "config_ids": config_ids,
        "pass_at_1": pass_at_1,
    }

    report["friedman_capability"] = capability_friedman(configs, levels or {"L3", "L4", "L5"})

    if len(config_ids) >= 3:
        aligned_all = align_tasks(configs, levels, require_all=True)
        report["n_tasks_aligned"] = len(aligned_all)
        report["friedman_all"] = friedman_test(aligned_all, config_ids)
        if report["friedman_all"].get("significant"):
            report["posthoc_wilcoxon"] = posthoc_wilcoxon(aligned_all, config_ids)

    report["evolution_ablation"] = evolution_ablation(configs, levels or {"L3", "L4", "L5"})

    report["token_analysis"] = token_analysis(configs, levels or {"L3", "L4", "L5"})

    report["quality_cost"] = quality_cost_analysis(pass_at_1)

    report["task_score_matrix"] = _build_task_score_matrix(configs, levels)

    return report


def print_report(report: dict) -> None:
    """Formatierte Terminal-Ausgabe."""
    print("\n" + "=" * 70)
    print("  MODELLVERGLEICH — STATISTISCHE AUSWERTUNG")
    print("=" * 70)

    n_aligned = report.get("n_tasks_aligned", len(report.get("task_score_matrix", {})))
    print(f"\nConfigs: {report['n_configs']}, Aligned Tasks: {n_aligned}")

    print(f"\n{'Config':<25} {'Pass@1':>8} {'Score':>8} {'CI95':>16} {'Cost $':>8} {'Q/$':>8}")
    print("-" * 78)
    qc = report.get("quality_cost", {}).get("configs", {})
    for cid, stats in sorted(report["pass_at_1"].items()):
        ci = stats.get("ci_95", [0, 0])
        ratio = qc.get(cid, {}).get("quality_cost_ratio", 0)
        print(f"{cid:<25} {stats['pass_at_1']:>7.1%} {stats['mean_score']:>8.3f} "
              f"[{ci[0]:.3f}, {ci[1]:.3f}] ${stats['cost_mean']:>7.4f} {ratio:>7.1f}")

    all_levels = sorted({lv for s in report["pass_at_1"].values() for lv in s.get("per_level", {})})
    if all_levels:
        print(f"\n{'Config':<25}", end="")
        for lv in all_levels:
            print(f" {lv:>8}", end="")
        print()
        print("-" * (25 + 9 * len(all_levels)))
        for cid, stats in sorted(report["pass_at_1"].items()):
            print(f"{cid:<25}", end="")
            for lv in all_levels:
                lv_stats = stats.get("per_level", {}).get(lv)
                if lv_stats:
                    print(f" {lv_stats['pass_at_1']:>7.1%}", end="")
                else:
                    print(f" {'—':>8}", end="")
            print()

    fc = report.get("friedman_capability", {})
    if "error" not in fc:
        sig = "SIGNIFIKANT" if fc.get("significant") else "nicht signifikant"
        print(f"\nCapability-Friedman: χ²={fc.get('statistic', '?')}, "
              f"p={fc.get('p_value', '?')}, n={fc.get('n_tasks', '?')} Tasks → {sig}")
        if "posthoc" in fc:
            for ph in fc["posthoc"]:
                if "error" in ph:
                    continue
                sig_mark = "***" if ph["significant"] else "n.s."
                print(f"  {ph['comparison']}: p_bonf={ph['p_bonferroni']:.4f} {sig_mark}, "
                      f"r={ph['rank_biserial']:+.3f} ({ph['direction']})")
    elif "error" in fc:
        print(f"\nCapability-Friedman: {fc['error']}")

    print(f"\nEvolution-Ablation:")
    for r in report.get("evolution_ablation", []):
        if "error" in r:
            print(f"  {r['tier']}: {r['error']}")
        else:
            sig_mark = "***" if r.get("significant") else "n.s."
            print(f"  {r['tier']}: Δ={r['delta_pass_at_1']:+.1%} (p={r['p_value']:.4f} {sig_mark}, "
                  f"r={r['effect_size']:+.3f}, {r['effect_direction']})")

    ta = report.get("token_analysis", {})
    if ta.get("thinking_token_ratio"):
        print(f"\nThinking-Token-Anteil:")
        for tier, ratio in ta["thinking_token_ratio"].items():
            print(f"  {tier}: {ratio:.1%}")

    qc_data = report.get("quality_cost", {})
    pareto = qc_data.get("pareto_frontier", [])
    if pareto:
        print(f"\nPareto-optimale Configs: {', '.join(pareto)}")

    print()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Modellvergleich — Statistische Auswertung")
    p.add_argument("--results", required=True,
                   help="Verzeichnis mit Seed-Result-JSONs")
    p.add_argument("--output", default=None,
                   help="Verzeichnis für Analyse-Output (statistics.json)")
    p.add_argument("--plots", default=None,
                   help="Verzeichnis für Plot-Output (→ plot_comparison.py)")
    p.add_argument("--levels", default=None,
                   help="Komma-separierter Level-Filter (z.B. 'L3,L4,L5')")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    levels = {l.strip() for l in args.levels.split(",")} if args.levels else None

    configs = load_results_dir(args.results)
    print(f"Geladen: {len(configs)} Configs, {sum(len(v) for v in configs.values())} Runs")
    for cid, runs in sorted(configs.items()):
        print(f"  {cid}: {len(runs)} seeds")

    report = build_report(configs, levels)
    print_report(report)

    if args.output:
        out_dir = Path(args.output)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "statistics.json"
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        print(f"Statistik-Report: {out_path}")

    if args.plots:
        print(f"\nPlots generieren: {args.plots}")
        from scripts.evaluation.plot_comparison import generate_all_plots
        generate_all_plots(report, args.plots)


if __name__ == "__main__":
    main()
