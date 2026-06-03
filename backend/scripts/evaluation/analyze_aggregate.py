from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scipy.stats import wilcoxon


def load_aggregate(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Aggregate not found: {p}")
    with open(p) as f:
        return json.load(f)


def _per_seed_pass_counts(agg: dict) -> list[int]:
    """Anzahl bestandener Tasks pro Seed (über task_pass_matrix)."""
    matrix = agg.get("task_pass_matrix") or {}
    if not matrix:
        return []
    n_seeds = len(next(iter(matrix.values())))
    return [sum(row[i] for row in matrix.values()) for i in range(n_seeds)]


def _rank_biserial(diffs: list[float]) -> float:
    """Rank-biserial Correlation als Effekt-Größe für Wilcoxon."""
    nonzero = [d for d in diffs if d != 0]
    if not nonzero:
        return 0.0
    ranks = sorted(nonzero, key=abs)
    abs_ranks = {}
    for i, v in enumerate(ranks, start=1):
        abs_ranks.setdefault(abs(v), []).append(i)
    pos_sum = neg_sum = 0.0
    for v in nonzero:
        r = abs_ranks[abs(v)].pop(0)
        if v > 0:
            pos_sum += r
        else:
            neg_sum += r
    total = pos_sum + neg_sum
    return (pos_sum - neg_sum) / total if total else 0.0


def compare(a: dict, b: dict, label_a: str, label_b: str) -> dict:
    counts_a = _per_seed_pass_counts(a)
    counts_b = _per_seed_pass_counts(b)
    if not counts_a or not counts_b:
        raise ValueError("Beide Aggregate brauchen task_pass_matrix mit Seeds.")

    matrix_a = a["task_pass_matrix"]
    matrix_b = b["task_pass_matrix"]
    common_tasks = sorted(set(matrix_a) & set(matrix_b))
    if not common_tasks:
        raise ValueError("Keine gemeinsamen Tasks zwischen den Aggregaten.")

    n_a = len(matrix_a[common_tasks[0]])
    n_b = len(matrix_b[common_tasks[0]])
    means_a = [sum(matrix_a[t]) / n_a for t in common_tasks]
    means_b = [sum(matrix_b[t]) / n_b for t in common_tasks]
    diffs = [ma - mb for ma, mb in zip(means_a, means_b)]

    nonzero_diffs = [d for d in diffs if d != 0]
    if nonzero_diffs:
        try:
            w_stat, p_value = wilcoxon(means_a, means_b, zero_method="wilcox")
        except ValueError:
            w_stat, p_value = float("nan"), 1.0
    else:
        w_stat, p_value = 0.0, 1.0

    effect = _rank_biserial(diffs)

    def _summary(agg: dict, label: str) -> dict:
        return {
            "label": label,
            "seeds": agg.get("seeds"),
            "pass_at_1_mean": agg.get("pass_at_1_mean"),
            "pass_at_1_std": agg.get("pass_at_1_std"),
            "pass_at_1_per_seed": agg.get("pass_at_1_per_seed"),
            "tokens_total_per_seed": agg.get("tokens_total_per_seed"),
            "duration_ms_per_seed": agg.get("duration_ms_per_seed"),
        }

    return {
        "a": _summary(a, label_a),
        "b": _summary(b, label_b),
        "common_tasks": len(common_tasks),
        "wilcoxon": {
            "statistic": float(w_stat) if w_stat == w_stat else None,
            "p_value": float(p_value),
            "interpretation": (
                "signifikant (p < 0.05)" if p_value < 0.05 else "nicht signifikant"
            ),
        },
        "effect_size_rank_biserial": round(effect, 4),
    }


def print_report(report: dict) -> None:
    a, b = report["a"], report["b"]
    print(f"\n=== Vergleich: {a['label']} vs. {b['label']} ===")
    print(f"Tasks gemeinsam: {report['common_tasks']}")
    print()
    print(f"{a['label']:>12}: Pass@1 = {a['pass_at_1_mean']:.3f} ± {a['pass_at_1_std']:.3f} "
          f"(seeds={a['seeds']}, per-seed={a['pass_at_1_per_seed']})")
    print(f"{b['label']:>12}: Pass@1 = {b['pass_at_1_mean']:.3f} ± {b['pass_at_1_std']:.3f} "
          f"(seeds={b['seeds']}, per-seed={b['pass_at_1_per_seed']})")
    print()

    if a.get("tokens_total_per_seed") and b.get("tokens_total_per_seed"):
        ta = sum(a["tokens_total_per_seed"]) / len(a["tokens_total_per_seed"])
        tb = sum(b["tokens_total_per_seed"]) / len(b["tokens_total_per_seed"])
        print(f"Tokens (mean): {a['label']}={ta:.0f}  {b['label']}={tb:.0f}  "
              f"Δ={(ta - tb):+.0f}")
    if a.get("duration_ms_per_seed") and b.get("duration_ms_per_seed"):
        da = sum(a["duration_ms_per_seed"]) / len(a["duration_ms_per_seed"])
        db = sum(b["duration_ms_per_seed"]) / len(b["duration_ms_per_seed"])
        print(f"Duration (mean ms): {a['label']}={da:.0f}  {b['label']}={db:.0f}  "
              f"Δ={(da - db):+.0f}")

    w = report["wilcoxon"]
    print()
    print(f"Wilcoxon Signed-Rank (paired by task):")
    print(f"  statistic = {w['statistic']}")
    print(f"  p-value   = {w['p_value']:.4f} → {w['interpretation']}")
    print(f"  effect    = {report['effect_size_rank_biserial']:+.3f} (rank-biserial)")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Aggregate-Vergleich mit Wilcoxon")
    p.add_argument("--a", required=True, help="Pfad zu Aggregat-JSON A")
    p.add_argument("--label-a", default="A", help="Label für A in Report")
    p.add_argument("--b", required=True, help="Pfad zu Aggregat-JSON B")
    p.add_argument("--label-b", default="B", help="Label für B in Report")
    p.add_argument("--out", default=None, help="Optional: Report-JSON-Pfad")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    a = load_aggregate(args.a)
    b = load_aggregate(args.b)
    report = compare(a, b, args.label_a, args.label_b)
    print_report(report)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\nReport JSON: {args.out}")


if __name__ == "__main__":
    main()
