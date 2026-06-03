from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import seaborn as sns

LAYER_COLORS = {
    "ast_only": "#4878CF",
    "alignment_only": "#E8822A",
    "combined": "#6AB162",
}

LAYER_LABELS = {
    "ast_only": "L1: AST",
    "alignment_only": "L2+L3: Alignment",
    "combined": "Combined",
}

LAYER_LABELS_DE = {
    "ast_only": "Nur AST (statisch)",
    "alignment_only": "Nur Alignment (semantisch)",
    "combined": "Kombiniert (AST + Alignment)",
}

METRIC_LABELS_DE = {
    "precision": "Precision\n(wie viele Treffer korrekt)",
    "recall": "Recall\n(wie viele Gefahren erkannt)",
    "f1": "F1\n(Balance aus beidem)",
}

CAT_ORDER = ["safe", "unsafe", "bypass", "semantic", "deception"]
CAT_LABELS = {
    "safe": "Safe (20)",
    "unsafe": "Unsafe (20)",
    "bypass": "Bypass (5)",
    "semantic": "Semantic (5)",
    "deception": "Deception (5)",
}

CAT_COLORS = {
    "safe": "#6AB162",
    "unsafe": "#CF4848",
    "bypass": "#E8822A",
    "semantic": "#9B59B6",
    "deception": "#3498DB",
}


def _savefig(fig, output_dir: str, name: str) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        path = out / f"{name}.{ext}"
        fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  {name}.pdf/png")


def plot_layer_comparison(report: dict, output_dir: str) -> None:
    """Schicht-Vergleich (RQ3-Hauptgrafik): Precision/Recall/F1 je Prüfschicht.

    Kernaussage visuell hervorgehoben: Reine AST-Analyse ist perfekt präzise,
    übersieht aber fast die Hälfte der Gefahren (niedriger Recall). Erst die
    semantische Alignment-Schicht hebt den Recall drastisch an.
    """
    layers = report.get("layers", {})
    layer_ids = ["ast_only", "alignment_only", "combined"]
    metrics_keys = ["precision", "recall", "f1"]

    fig, ax = plt.subplots(figsize=(9.5, 6.2))
    x = np.arange(len(metrics_keys))
    width = 0.26
    offsets = [-width, 0, width]

    values: dict[str, dict[str, float]] = {}
    for i, lid in enumerate(layer_ids):
        m = layers.get(lid, {})
        vals, errs = [], []
        for mk in metrics_keys:
            entry = m.get(mk, {})
            if isinstance(entry, dict):
                vals.append(entry.get("mean", 0))
                errs.append(entry.get("std", 0))
            else:
                vals.append(float(entry))
                errs.append(0)
        values[lid] = dict(zip(metrics_keys, vals))

        bars = ax.bar(x + offsets[i], vals, width,
                      color=LAYER_COLORS[lid], alpha=0.9,
                      label=LAYER_LABELS_DE[lid], yerr=errs,
                      capsize=4, error_kw={"linewidth": 1.2},
                      edgecolor="black", linewidth=0.5)

        for bar, val, err in zip(bars, vals, errs):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + err + 0.015,
                    f"{val:.0%}", ha="center", va="bottom",
                    fontsize=9.5, fontweight="bold")

    ri = metrics_keys.index("recall")
    ast_recall = values["ast_only"]["recall"]
    comb_recall = values["combined"]["recall"]
    ax.annotate("", xy=(ri + width, comb_recall + 0.11),
                xytext=(ri - width, ast_recall + 0.05),
                arrowprops=dict(arrowstyle="-|>", color="#CF4848", lw=2.2,
                                connectionstyle="arc3,rad=-0.35"))
    ax.text(ri, comb_recall + 0.17,
            f"+{(comb_recall - ast_recall) * 100:.0f} pp Recall\n"
            "durch die semantische Schicht",
            ha="center", va="bottom", fontsize=10, fontweight="bold",
            color="#CF4848")

    ax.text(ri - width, ast_recall - 0.05,
            f"übersieht\n{(1 - ast_recall) * 100:.0f} %",
            ha="center", va="top", fontsize=9, color="white",
            fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels([METRIC_LABELS_DE[mk] for mk in metrics_keys], fontsize=10)
    ax.set_ylabel("Score (höher = besser)", fontsize=11)
    ax.set_title("Gatekeeper: Was bringt die semantische Prüfschicht?\n"
                 "(55 Code-Beschreibung-Paare, 3 Runs)", fontsize=13)
    ax.set_ylim(0, 1.22)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax.legend(fontsize=10, loc="upper center", bbox_to_anchor=(0.5, -0.13),
              ncol=3, frameon=False)
    ax.grid(axis="y", alpha=0.3)
    sns.despine()
    fig.tight_layout()

    _savefig(fig, output_dir, "07_gatekeeper_layer_comparison")


def plot_category_heatmap(report: dict, output_dir: str) -> None:
    per_cat = report.get("per_category_summary", {})
    if not per_cat:
        return

    layer_keys = ["ast_correct", "alignment_correct", "combined_correct"]
    layer_labels_short = ["AST", "Alignment", "Combined"]
    cats = [c for c in CAT_ORDER if c in per_cat]

    matrix = np.zeros((len(cats), len(layer_keys)))
    annot = [[""]*len(layer_keys) for _ in range(len(cats))]

    for i, cat in enumerate(cats):
        n = per_cat[cat]["n"]
        for j, lk in enumerate(layer_keys):
            val_str = per_cat[cat].get(lk, "0/0")
            numerator = val_str.split("/")[0].split("±")[0]
            try:
                correct = float(numerator)
            except ValueError:
                correct = 0
            matrix[i, j] = correct / n if n else 0
            annot[i][j] = val_str

    fig, ax = plt.subplots(figsize=(7, 5))
    sns.heatmap(matrix, annot=annot, fmt="",
                cmap="RdYlGn", vmin=0, vmax=1,
                xticklabels=layer_labels_short,
                yticklabels=[CAT_LABELS.get(c, c) for c in cats],
                ax=ax, linewidths=0.8, cbar_kws={"label": "Erkennungsrate"},
                annot_kws={"fontsize": 11, "fontweight": "bold"})

    ax.set_title("Erkennungsrate pro Kategorie × Layer", fontsize=13)
    ax.tick_params(axis="both", labelsize=10)

    _savefig(fig, output_dir, "08_gatekeeper_category_heatmap")


def plot_threshold_sweep(report: dict, output_dir: str) -> None:
    """Schwellwert-Trade-off (RQ3): Erkennung, Fehlalarme und F1 je Schwellwert.

    Einzelpanel im Stil der übrigen RQ-Grafiken: Erkennungsrate (TPR, grün) und
    Fehlalarmrate (FPR, rot) laufen gegenläufig; F1 (blau) markiert das Optimum.
    Der gewählte Schwellwert t=0.7 ist als senkrechte Linie hervorgehoben.
    """
    sweep = report.get("threshold_sweep", [])
    if not sweep:
        return

    thresholds = [s["threshold"] for s in sweep]
    tprs = [s.get("tpr_mean", s.get("tpr", 0)) for s in sweep]
    fprs = [s.get("fpr_mean", s.get("fpr", 0)) for s in sweep]
    f1s = [s.get("f1_mean", s.get("f1", 0)) for s in sweep]
    tpr_stds = [s.get("tpr_std", 0) for s in sweep]
    fpr_stds = [s.get("fpr_std", 0) for s in sweep]
    f1_stds = [s.get("f1_std", 0) for s in sweep]

    fig, ax = plt.subplots(figsize=(9, 5.6))

    idx_07 = thresholds.index(0.7) if 0.7 in thresholds else -1

    if idx_07 >= 0:
        ax.axvline(x=0.7, color="#888888", linestyle="--", linewidth=1.4,
                   alpha=0.7, zorder=1)

    ax.errorbar(thresholds, tprs, yerr=tpr_stds, fmt="o-", color="#2E7D32",
                linewidth=2.4, markersize=9, capsize=4, elinewidth=1.1,
                markeredgecolor="black", markeredgewidth=0.5, zorder=4,
                label="Erkennungsrate (TPR) — mehr = besser")
    ax.errorbar(thresholds, fprs, yerr=fpr_stds, fmt="s--", color="#CF4848",
                linewidth=2.4, markersize=8, capsize=4, elinewidth=1.1,
                markeredgecolor="black", markeredgewidth=0.5, zorder=4,
                label="Fehlalarmrate (FPR) — weniger = besser")
    ax.errorbar(thresholds, f1s, yerr=f1_stds, fmt="D-", color="#4878CF",
                linewidth=2.4, markersize=8, capsize=4, elinewidth=1.1,
                markeredgecolor="black", markeredgewidth=0.5, zorder=4,
                label="F1 (Balance)")

    if idx_07 >= 0:
        ax.scatter([0.7], [f1s[idx_07]], color="#4878CF", s=260, zorder=6,
                   marker="*", edgecolors="black", linewidth=0.9)
        ax.annotate(f"gewählter Schwellwert t=0.7\nF1 = {f1s[idx_07]:.2f}",
                    (0.7, f1s[idx_07]), textcoords="offset points",
                    xytext=(12, 14), fontsize=10, fontweight="bold",
                    color="#333333")

    ax.set_xlabel("Alignment-Schwellwert", fontsize=11)
    ax.set_ylabel("Rate (höher = besser, außer FPR)", fontsize=11)
    ax.set_title("Gatekeeper: Erkennung vs. Fehlalarme je Schwellwert\n"
                 "(nur semantische Schicht, 3 Runs)", fontsize=13)
    ax.set_xlim(0.45, 0.95)
    ax.set_ylim(-0.05, 1.08)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax.legend(fontsize=10, loc="center left", frameon=True, framealpha=0.9)
    ax.grid(alpha=0.3)
    sns.despine()
    fig.tight_layout()

    _savefig(fig, output_dir, "09_gatekeeper_threshold_sweep")


def plot_score_distribution(report: dict, output_dir: str) -> None:
    variance = report.get("variance", {})
    per_skill = variance.get("per_skill", [])
    if not per_skill:
        return

    def get_cat(sid: str) -> str:
        for prefix in ("safe_", "unsafe_", "bypass_", "semantic_", "deception_"):
            if sid.startswith(prefix):
                return prefix.rstrip("_")
        return "unknown"

    fig, ax = plt.subplots(figsize=(10, 5))

    cat_scores: dict[str, list[float]] = {}
    for p in per_skill:
        cat = get_cat(p["skill_id"])
        for s in p["scores"]:
            cat_scores.setdefault(cat, []).append(s)

    positions = []
    labels = []
    all_data = []
    colors = []

    for i, cat in enumerate(CAT_ORDER):
        if cat in cat_scores:
            positions.append(i)
            labels.append(CAT_LABELS.get(cat, cat))
            all_data.append(cat_scores[cat])
            colors.append(CAT_COLORS.get(cat, "#999"))

    parts = ax.violinplot(all_data, positions=positions, showmeans=True,
                          showmedians=True, widths=0.7)

    for i, pc in enumerate(parts["bodies"]):
        pc.set_facecolor(colors[i])
        pc.set_alpha(0.6)

    for key in ("cmeans", "cmedians", "cbars", "cmins", "cmaxes"):
        if key in parts:
            parts[key].set_color("black")
            parts[key].set_linewidth(1)

    for i, (pos, scores) in enumerate(zip(positions, all_data)):
        jitter = np.random.default_rng(42).uniform(-0.15, 0.15, len(scores))
        ax.scatter([pos + j for j in jitter], scores, color=colors[i],
                   s=25, alpha=0.7, edgecolors="black", linewidth=0.3, zorder=5)

    ax.axhline(y=0.7, color="red", linestyle="--", linewidth=1.5, alpha=0.7,
               label="Threshold (0.7)")

    ax.set_xticks(positions)
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel("Alignment Score", fontsize=11)
    ax.set_title("Alignment-Score-Verteilung pro Kategorie (3 Runs)", fontsize=13)
    ax.set_ylim(-0.05, 1.05)
    ax.legend(fontsize=9, loc="lower left")
    ax.grid(axis="y", alpha=0.3)
    sns.despine()

    _savefig(fig, output_dir, "10_gatekeeper_score_distribution")


def generate_all_plots(report: dict, output_dir: str) -> None:
    print(f"Gatekeeper-Plots → {output_dir}/")
    plot_layer_comparison(report, output_dir)
    plot_category_heatmap(report, output_dir)
    plot_threshold_sweep(report, output_dir)
    plot_score_distribution(report, output_dir)
    print("  4 Gatekeeper-Plots generiert")


def main() -> None:
    p = argparse.ArgumentParser(description="Gatekeeper RQ3 — Plot-Generierung")
    p.add_argument("--report", required=True, help="Pfad zu gatekeeper_final.json")
    p.add_argument("--output", required=True, help="Verzeichnis fuer Plot-Output")
    args = p.parse_args()

    with open(args.report) as f:
        report = json.load(f)
    generate_all_plots(report, args.output)


if __name__ == "__main__":
    main()
