from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path


def load_runs(paths: list[str]) -> list[dict]:
    runs = []
    for p in sorted(paths):
        with open(p) as f:
            runs.append(json.load(f))
    return runs


def extract_alignment_scores(runs: list[dict]) -> dict[str, list[float]]:
    """Pro Skill: Liste der Alignment-Scores ueber alle Runs."""
    scores: dict[str, list[float]] = {}
    for run in runs:
        results = run.get("per_skill_results", {})
        alignment = results.get("alignment", results) if isinstance(results, dict) else results
        if isinstance(alignment, list):
            for r in alignment:
                sid = r["skill_id"]
                scores.setdefault(sid, []).append(r.get("alignment_score", 0.0))
    return scores


def extract_classifications(runs: list[dict], layer: str = "alignment") -> dict[str, list[str]]:
    """Pro Skill: Liste der Klassifikationen (TP/TN/FP/FN) ueber alle Runs."""
    classifications: dict[str, list[str]] = {}
    for run in runs:
        results = run.get("per_skill_results", {})
        data = results.get(layer, results) if isinstance(results, dict) else results
        if isinstance(data, list):
            for r in data:
                sid = r["skill_id"]
                classifications.setdefault(sid, []).append(r["classification"])
    return classifications


def compute_variance_stats(runs: list[dict]) -> dict:
    scores = extract_alignment_scores(runs)
    classifications = extract_classifications(runs)
    n_runs = len(runs)

    per_skill = []
    stable_count = 0
    for sid in sorted(scores.keys()):
        s = scores[sid]
        c = classifications.get(sid, [])
        mean_score = statistics.mean(s) if s else 0.0
        std_score = statistics.stdev(s) if len(s) > 1 else 0.0
        all_same = len(set(c)) == 1
        if all_same:
            stable_count += 1
        per_skill.append({
            "skill_id": sid,
            "mean_score": round(mean_score, 4),
            "std_score": round(std_score, 4),
            "scores": [round(x, 4) for x in s],
            "classifications": c,
            "stable": all_same,
        })

    total_skills = len(per_skill)
    return {
        "n_runs": n_runs,
        "score_stability": round(stable_count / total_skills, 4) if total_skills else 0.0,
        "classification_agreement": round(stable_count / total_skills, 4) if total_skills else 0.0,
        "mean_std_across_skills": round(
            statistics.mean(p["std_score"] for p in per_skill), 4
        ) if per_skill else 0.0,
        "per_skill": per_skill,
    }


def aggregate_layer_metrics(runs: list[dict], layer: str) -> dict:
    """Mittelwert +/- Std ueber Runs fuer eine Layer-Metrik."""
    values: dict[str, list[float]] = {}
    for run in runs:
        metrics = run.get("layers", {}).get(layer, {}).get("metrics", {})
        for k, v in metrics.items():
            if isinstance(v, (int, float)):
                values.setdefault(k, []).append(float(v))

    aggregated = {}
    for k, vals in values.items():
        mean = statistics.mean(vals)
        std = statistics.stdev(vals) if len(vals) > 1 else 0.0
        aggregated[k] = {"mean": round(mean, 4), "std": round(std, 4)}
    return aggregated


def aggregate_sweep(runs: list[dict]) -> list[dict]:
    """Mittelwert ueber Runs fuer jedes Threshold im Sweep."""
    sweep_by_threshold: dict[float, dict[str, list[float]]] = {}
    for run in runs:
        for entry in run.get("threshold_sweep", []):
            t = entry["threshold"]
            sweep_by_threshold.setdefault(t, {})
            for k in ("tpr", "fpr", "f1", "precision", "recall", "accuracy"):
                sweep_by_threshold[t].setdefault(k, []).append(entry.get(k, 0.0))

    result = []
    for t in sorted(sweep_by_threshold.keys()):
        row = {"threshold": t}
        for k, vals in sweep_by_threshold[t].items():
            row[f"{k}_mean"] = round(statistics.mean(vals), 4)
            row[f"{k}_std"] = round(statistics.stdev(vals) if len(vals) > 1 else 0.0, 4)
        result.append(row)
    return result


def print_thesis_tables(final: dict):
    """Druckt Thesis-fertige Markdown-Tabellen."""
    print("\n" + "=" * 70)
    print("TABELLE 1: Layer-Vergleich (Gesamt)")
    print("=" * 70)
    header = "| Layer | TP | TN | FP | FN | Precision | Recall | F1 | Accuracy |"
    sep = "|" + "|".join(["---"] * 9) + "|"
    print(header)
    print(sep)
    for layer_name in ("ast_only", "alignment_only", "combined"):
        m = final["layers"].get(layer_name, {})
        if not m:
            continue
        def v(key):
            entry = m.get(key, {})
            if isinstance(entry, dict):
                mean = entry.get("mean", 0)
                std = entry.get("std", 0)
                if key in ("tp", "tn", "fp", "fn"):
                    return f"{mean:.0f}"
                return f"{mean:.3f}" if std < 0.01 else f"{mean:.3f}±{std:.3f}"
            return f"{entry}"
        label = {"ast_only": "AST-Only", "alignment_only": "Alignment-Only", "combined": "Combined"}
        print(f"| {label.get(layer_name, layer_name)} | {v('tp')} | {v('tn')} | {v('fp')} | {v('fn')} | {v('precision')} | {v('recall')} | {v('f1')} | {v('accuracy')} |")

    print("\n" + "=" * 70)
    print("TABELLE 2: Per-Kategorie-Erkennung")
    print("=" * 70)
    if "per_category_summary" in final:
        header2 = "| Kategorie | n | AST erkannt | Alignment erkannt | Combined |"
        sep2 = "|" + "|".join(["---"] * 5) + "|"
        print(header2)
        print(sep2)
        for cat, data in sorted(final["per_category_summary"].items()):
            n = data.get("n", 0)
            ast_ok = data.get("ast_correct", "?")
            align_ok = data.get("alignment_correct", "?")
            comb_ok = data.get("combined_correct", "?")
            print(f"| {cat} | {n} | {ast_ok} | {align_ok} | {comb_ok} |")

    print("\n" + "=" * 70)
    print("TABELLE 3: Threshold-Sweep")
    print("=" * 70)
    header3 = "| Threshold | TPR (Recall) | FPR | F1 |"
    sep3 = "|" + "|".join(["---"] * 4) + "|"
    print(header3)
    print(sep3)
    for s in final.get("threshold_sweep", []):
        tpr = s.get("tpr_mean", s.get("tpr", 0))
        fpr = s.get("fpr_mean", s.get("fpr", 0))
        f1 = s.get("f1_mean", s.get("f1", 0))
        tpr_std = s.get("tpr_std", 0)
        fpr_std = s.get("fpr_std", 0)
        f1_std = s.get("f1_std", 0)
        def fmt(mean, std):
            return f"{mean:.3f}" if std < 0.01 else f"{mean:.3f}±{std:.3f}"
        print(f"| {s['threshold']:.1f} | {fmt(tpr, tpr_std)} | {fmt(fpr, fpr_std)} | {fmt(f1, f1_std)} |")

    if "variance" in final:
        v = final["variance"]
        print(f"\n--- Varianz-Analyse ({v['n_runs']} Runs) ---")
        print(f"  Stabilitaet: {v['score_stability']*100:.1f}% Skills mit gleichem Ergebnis in allen Runs")
        print(f"  Mittlere Std Alignment-Score: {v['mean_std_across_skills']:.4f}")


def build_per_category_summary(runs: list[dict]) -> dict:
    """Baut Kategorie-Zusammenfassung gemittelt ueber alle Runs."""
    cats: dict[str, dict[str, list[int]]] = {}

    for run in runs:
        for layer_name in ("ast_only", "alignment_only", "combined"):
            per_cat = run.get("layers", {}).get(layer_name, {}).get("per_category", {})
            for cat, m in per_cat.items():
                cats.setdefault(cat, {"n": m["total"]})
                correct = m["tp"] + m["tn"]
                cats[cat].setdefault(f"{layer_name}_vals", []).append(correct)

    renamed = {}
    for cat, data in cats.items():
        n = data["n"]
        def fmt(key):
            vals = data.get(f"{key}_vals", [])
            if not vals:
                return "?"
            mean = statistics.mean(vals)
            std = statistics.stdev(vals) if len(vals) > 1 else 0.0
            if std == 0:
                return f"{int(mean)}/{n}"
            return f"{mean:.1f}±{std:.1f}/{n}"

        renamed[cat] = {
            "n": n,
            "ast_correct": fmt("ast_only"),
            "alignment_correct": fmt("alignment_only"),
            "combined_correct": fmt("combined"),
        }
    return renamed


def main():
    parser = argparse.ArgumentParser(description="Gatekeeper Varianz-Analyse (Sprint 6.2)")
    parser.add_argument("runs", nargs="+", help="JSON-Dateien der einzelnen Runs")
    parser.add_argument("--output", default="results/thesis/gatekeeper/gatekeeper_final.json")
    args = parser.parse_args()

    runs = load_runs(args.runs)
    print(f"Analysiere {len(runs)} Run(s)...")

    variance = compute_variance_stats(runs)
    print(f"  Stabilitaet: {variance['score_stability']*100:.1f}%")
    print(f"  Mittlere Std: {variance['mean_std_across_skills']:.4f}")

    final = {
        "evaluation": "gatekeeper_rq3_final",
        "n_runs": len(runs),
        "corpus_size": runs[0].get("corpus_size", 55),
        "layers": {
            layer: aggregate_layer_metrics(runs, layer)
            for layer in ("ast_only", "alignment_only", "combined")
        },
        "threshold_sweep": aggregate_sweep(runs),
        "variance": {
            "n_runs": variance["n_runs"],
            "score_stability": variance["score_stability"],
            "classification_agreement": variance["classification_agreement"],
            "mean_std_across_skills": variance["mean_std_across_skills"],
            "per_skill": variance["per_skill"],
        },
        "per_category_summary": build_per_category_summary(runs),
    }

    print_thesis_tables(final)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(final, f, indent=2, ensure_ascii=False)
    print(f"\nFinales JSON gespeichert: {out_path}")


if __name__ == "__main__":
    main()
