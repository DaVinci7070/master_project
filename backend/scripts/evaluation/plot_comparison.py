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

TIER_COLORS = {
    "U-WEAK-FULL": "#4878CF",
    "ABL-WEAK-EVO-ON": "#4878CF",
    "ABL-WEAK-EVO-OFF": "#6C95CE",
    "U-MEDIUM-L3L5": "#E8822A",
    "U-STRONG-L3L5": "#6AB162",
    "ABL-STRONG-EVO-ON": "#6AB162",
    "ABL-STRONG-EVO-OFF": "#8FCA88",
}

TIER_LABELS = {
    "U-WEAK-FULL": "T-Weak\n(2.0-flash)",
    "ABL-WEAK-EVO-ON": "T-Weak\n(EVO ON)",
    "ABL-WEAK-EVO-OFF": "T-Weak\n(EVO OFF)",
    "U-MEDIUM-L3L5": "T-Medium\n(2.5-flash)",
    "U-STRONG-L3L5": "T-Strong\n(3.5-flash)",
    "ABL-STRONG-EVO-ON": "T-Strong\n(EVO ON)",
    "ABL-STRONG-EVO-OFF": "T-Strong\n(EVO OFF)",
}

CAPABILITY_ORDER = ["ABL-WEAK-EVO-ON", "U-MEDIUM-L3L5", "U-STRONG-L3L5"]

TIER_MODEL_NAMES = {
    "Weak": "Gemini 2.0 Flash",
    "Medium": "Gemini 2.5 Flash",
    "Strong": "Gemini 3.5 Flash",
}

EVO_ON_COLOR = "#2E7D32"
EVO_OFF_COLOR = "#B0B0B0"


def _tier_model_name(tier: str) -> str:
    return TIER_MODEL_NAMES.get(tier, tier)


def _get_color(config_id: str) -> str:
    return TIER_COLORS.get(config_id, "#999999")


def _get_label(config_id: str) -> str:
    return TIER_LABELS.get(config_id, config_id)


def _savefig(fig, output_dir: str, name: str) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        path = out / f"{name}.{ext}"
        fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  {name}.pdf/png")


def plot_pass_at_1_boxplot(report: dict, output_dir: str) -> None:
    """Bar-Chart mit 95%-CI für Pass@1 der Capability-Study-Configs."""
    pass_data = report.get("pass_at_1", {})
    main_configs = [c for c in CAPABILITY_ORDER if c in pass_data]
    if not main_configs:
        main_configs = sorted(pass_data.keys())

    fig, ax = plt.subplots(figsize=(8, 5))

    for i, cid in enumerate(main_configs):
        stats = pass_data[cid]
        p1 = stats["pass_at_1"]
        ci = stats.get("ci_95", [p1, p1])
        ci_lower = max(0, p1 - ci[0])
        ci_upper = max(0, ci[1] - p1)

        ax.bar(i, p1, color=_get_color(cid), alpha=0.85, width=0.55)
        ax.errorbar(i, p1, yerr=[[ci_lower], [ci_upper]],
                    fmt="none", color="black", capsize=6, linewidth=1.5)
        ax.text(i, p1 + ci_upper + 0.02, f"{p1:.0%}",
                ha="center", va="bottom", fontsize=11, fontweight="bold")

    ax.set_xticks(range(len(main_configs)))
    ax.set_xticklabels([_get_label(c) for c in main_configs], fontsize=9)
    ax.set_ylabel("Pass@1", fontsize=11)
    ax.set_title("Pass@1 nach Modell-Tier (95% CI)", fontsize=13)
    ax.set_ylim(0, 1.15)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax.grid(axis="y", alpha=0.3)
    sns.despine()

    _savefig(fig, output_dir, "01_pass_at_1_boxplot")


PARETO_LABELS = {
    "ABL-STRONG-EVO-OFF": ("Strong · ohne Evolution", (8, 10, "left")),
    "ABL-WEAK-EVO-OFF": ("Weak · ohne Evolution", (8, -16, "left")),
    "ABL-WEAK-EVO-ON": ("Weak · mit Evolution", (8, 10, "left")),
    "U-MEDIUM-L3L5": ("Medium · Cold-Start", (10, -16, "left")),
    "U-STRONG-L3L5": ("Strong · Cold-Start", (-12, 8, "right")),
    "U-WEAK-FULL": ("Weak · Cold-Start", (10, -16, "left")),
    "CW-WEAK-WARM": ("Weak · Warm-Start", (10, 12, "left")),
}


def _pareto_label(cid: str) -> str:
    return PARETO_LABELS.get(cid, (cid, None))[0]


def _pareto_offset(cid: str) -> tuple[int, int, str]:
    return PARETO_LABELS.get(cid, (cid, (8, 6, "left")))[1]


def _pareto_tier_color(cid: str) -> str:
    if "STRONG" in cid:
        return "#6AB162"
    if "MEDIUM" in cid:
        return "#E8822A"
    return "#4878CF"


def _compute_pareto(points: dict[str, tuple[float, float]]) -> set[str]:
    """Nicht-dominierte Front: günstiger (x↓) UND besser (y↑) ist ideal.

    Ein Punkt ist dominiert, wenn ein anderer mindestens so günstig und
    mindestens so gut ist und in einem der beiden echt besser.
    """
    pareto = set()
    for cid, (cx, cy) in points.items():
        dominated = any(
            ox <= cx and oy >= cy and (ox < cx or oy > cy)
            for oid, (ox, oy) in points.items() if oid != cid
        )
        if not dominated:
            pareto.add(cid)
    return pareto


def plot_pareto(report: dict, output_dir: str) -> None:
    """Pareto-Frontier: Pass@1 (Qualität) vs. Kosten pro Run."""
    qc = report.get("quality_cost", {})
    configs_data = qc.get("configs", qc)
    if not configs_data or isinstance(next(iter(configs_data.values()), None), list):
        return

    points = {cid: (d["cost_mean"], d["pass_at_1"]) for cid, d in configs_data.items()}
    pareto_set = _compute_pareto(points)

    fig, ax = plt.subplots(figsize=(10, 6.2))

    pareto_pts = sorted((points[c] for c in pareto_set))
    if len(pareto_pts) > 1:
        px, py = zip(*pareto_pts)
        ax.fill_between(px, py, 0, color="#2E7D32", alpha=0.06, zorder=0)
        ax.plot(px, py, "-", color="#2E7D32", linewidth=2.0, alpha=0.7,
                zorder=2, label="Pareto-Front (optimal)")

    for cid, (cost, p1) in points.items():
        is_pareto = cid in pareto_set
        color = _pareto_tier_color(cid)
        ax.scatter(cost, p1, color=color, s=210 if is_pareto else 90,
                   marker="D" if is_pareto else "o", zorder=5,
                   edgecolors="black", linewidth=1.6 if is_pareto else 0.6,
                   alpha=1.0 if is_pareto else 0.55)
        dx, dy, ha = _pareto_offset(cid)
        label = _pareto_label(cid)
        ax.annotate(("★ " if is_pareto else "") + label, (cost, p1),
                    textcoords="offset points", xytext=(dx, dy), ha=ha,
                    fontsize=9, fontweight="bold" if is_pareto else "normal",
                    color="black" if is_pareto else "#555555")

    ax.annotate("Ideal:\nhohe Qualität,\ngeringe Kosten",
                xy=(0.02, 0.97), xycoords="axes fraction",
                ha="left", va="top", fontsize=9, color="#2E7D32",
                fontstyle="italic")

    from matplotlib.lines import Line2D
    tier_handles = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#4878CF",
               markersize=10, label="Weak (Gemini 2.0)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#E8822A",
               markersize=10, label="Medium (Gemini 2.5)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#6AB162",
               markersize=10, label="Strong (Gemini 3.5)"),
        Line2D([0], [0], marker="D", color="w", markerfacecolor="#999999",
               markeredgecolor="black", markersize=11,
               label="★ Pareto-optimal"),
    ]
    ax.legend(handles=tier_handles, fontsize=9, loc="lower right",
              frameon=True, framealpha=0.9)

    ax.set_xlabel("Kosten pro Run ($) — weiter links = günstiger", fontsize=11)
    ax.set_ylabel("Pass@1 (Erfolgsrate) — weiter oben = besser", fontsize=11)
    ax.set_title("Qualität vs. Kosten: Welche Konfiguration ist effizient?",
                 fontsize=13)
    ax.set_ylim(0.45, 0.92)
    ax.set_xlim(left=0.0)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax.grid(alpha=0.3)
    sns.despine()
    fig.tight_layout()

    _savefig(fig, output_dir, "02_pareto_quality_cost")


def plot_heatmap(report: dict, output_dir: str) -> None:
    """Heatmap: Tasks (Zeilen) × Configs (Spalten), Farbe = Mean-Score."""
    matrix_data = report.get("task_score_matrix", {})
    if not matrix_data:
        _plot_heatmap_level_fallback(report, output_dir)
        return

    config_ids = sorted({
        k for row in matrix_data.values()
        for k in row.keys() if k != "level"
    })
    if not config_ids:
        return

    task_ids = sorted(matrix_data.keys(), key=lambda t: (matrix_data[t].get("level", ""), t))

    matrix = np.array([
        [matrix_data[tid].get(cid, float("nan")) for cid in config_ids]
        for tid in task_ids
    ])

    short_ids = [tid.split("_", 1)[-1][:25] for tid in task_ids]
    level_labels = [matrix_data[tid].get("level", "?") for tid in task_ids]
    row_labels = [f"{lv} {sid}" for lv, sid in zip(level_labels, short_ids)]

    height = max(4, len(task_ids) * 0.35)
    width = max(6, len(config_ids) * 1.8)
    fig, ax = plt.subplots(figsize=(width, height))

    sns.heatmap(matrix, annot=True, fmt=".2f", cmap="RdYlGn", vmin=0, vmax=1,
                xticklabels=[_get_label(c).replace("\n", " ") for c in config_ids],
                yticklabels=row_labels, ax=ax, linewidths=0.5,
                cbar_kws={"label": "Score"})
    ax.set_title("Score pro Task × Config", fontsize=13)
    ax.tick_params(axis="y", labelsize=7)
    ax.tick_params(axis="x", labelsize=8)

    _savefig(fig, output_dir, "03_heatmap_task_config")


def _plot_heatmap_level_fallback(report: dict, output_dir: str) -> None:
    """Fallback: Level-aggregierte Heatmap wenn keine Task-Matrix vorhanden."""
    pass_data = report.get("pass_at_1", {})
    config_ids = sorted(pass_data.keys())
    if not config_ids:
        return

    levels_data = {}
    for cid in config_ids:
        for lv, lv_stats in pass_data[cid].get("per_level", {}).items():
            levels_data.setdefault(lv, {})[cid] = lv_stats.get("pass_at_1", 0)

    if not levels_data:
        return

    level_ids = sorted(levels_data.keys())
    matrix = np.array([[levels_data[lv].get(cid, float("nan")) for cid in config_ids]
                        for lv in level_ids])

    fig, ax = plt.subplots(figsize=(max(6, len(config_ids) * 1.5), max(3, len(level_ids) * 0.8)))
    sns.heatmap(matrix, annot=True, fmt=".0%", cmap="RdYlGn", vmin=0, vmax=1,
                xticklabels=[_get_label(c).replace("\n", " ") for c in config_ids],
                yticklabels=level_ids, ax=ax, linewidths=0.5)
    ax.set_title("Pass@1 nach Level × Config", fontsize=13)
    ax.set_ylabel("Level")
    ax.set_xlabel("Config")

    _savefig(fig, output_dir, "03_heatmap_task_config")


def plot_evolution_effect(report: dict, output_dir: str) -> None:
    """Gruppierter Bar-Chart: EVO ON vs OFF mit Δ Pass@1."""
    ablation = report.get("evolution_ablation", [])
    if isinstance(ablation, dict):
        ablation = list(ablation.values())
    if not ablation:
        return

    valid = [r for r in ablation if "error" not in r]
    if not valid:
        return

    fig, ax = plt.subplots(figsize=(8, 5))

    x = np.arange(len(valid))
    width = 0.35

    def _is_significant(v) -> bool:
        return str(v).lower() in ("true", "1", "yes")

    for i, r in enumerate(valid):
        p1_on = r.get("pass_at_1_on", 0)
        p1_off = r.get("pass_at_1_off", 0)

        ax.bar(i - width / 2, p1_on, width, color=EVO_ON_COLOR,
               label="Evolution AN" if i == 0 else "")
        ax.bar(i + width / 2, p1_off, width, color=EVO_OFF_COLOR,
               label="Evolution AUS" if i == 0 else "")

        ax.text(i - width / 2, p1_on + 0.015, f"{p1_on:.0%}",
                ha="center", va="bottom", fontsize=9)
        ax.text(i + width / 2, p1_off + 0.015, f"{p1_off:.0%}",
                ha="center", va="bottom", fontsize=9)

        delta = r.get("delta_pass_at_1", 0)
        sig = "p<0.05" if _is_significant(r.get("significant")) else "n.s."
        y_top = max(p1_on, p1_off) + 0.10
        ax.text(i, y_top, f"Δ = {delta:+.0%}\n({sig})",
                ha="center", va="bottom", fontsize=9, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels([_tier_model_name(r.get("tier", "?")) for r in valid],
                       fontsize=11)
    ax.set_ylabel("Pass@1 (Erfolgsrate)", fontsize=11)
    ax.set_title("Effekt der Selbst-Evolution: mit vs. ohne", fontsize=13)
    ax.set_ylim(0, 1.2)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax.legend(fontsize=10, loc="upper right")
    ax.grid(axis="y", alpha=0.3)
    sns.despine()

    _savefig(fig, output_dir, "04_evolution_effect")


def plot_pass_by_level(report: dict, output_dir: str) -> None:
    """Line-Plot: Pass@1 pro Komplexitäts-Level, eine Linie pro Config."""
    pass_data = report.get("pass_at_1", {})
    config_ids = sorted(pass_data.keys())

    all_levels = sorted({lv for s in pass_data.values() for lv in s.get("per_level", {})})
    if not all_levels:
        return

    fig, ax = plt.subplots(figsize=(8, 5))

    for cid in config_ids:
        x_vals, y_vals = [], []
        for i, lv in enumerate(all_levels):
            lv_stats = pass_data[cid].get("per_level", {}).get(lv)
            if lv_stats:
                x_vals.append(i)
                y_vals.append(lv_stats["pass_at_1"])

        ax.plot(x_vals, y_vals, "o-", color=_get_color(cid),
                label=_get_label(cid).replace("\n", " "), linewidth=2, markersize=8)

    ax.set_xticks(range(len(all_levels)))
    ax.set_xticklabels(all_levels, fontsize=10)
    ax.set_ylabel("Pass@1", fontsize=11)
    ax.set_xlabel("Komplexitäts-Level", fontsize=11)
    ax.set_title("Pass@1 nach Komplexitäts-Level", fontsize=13)
    ax.set_ylim(-0.05, 1.05)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax.legend(fontsize=8, loc="lower left")
    ax.grid(alpha=0.3)
    sns.despine()

    _savefig(fig, output_dir, "05_pass_by_level")


TOKENS_LABELS = {
    "ABL-WEAK-EVO-OFF": ("Weak · ohne Evolution", (10, -4, "left")),
    "ABL-STRONG-EVO-OFF": ("Strong · ohne Evolution", (10, 6, "left")),
    "ABL-WEAK-EVO-ON": ("Weak · mit Evolution", (10, 6, "left")),
    "U-MEDIUM-L3L5": ("Medium · Cold-Start", (0, -18, "center")),
    "U-STRONG-L3L5": ("Strong · Cold-Start", (0, 12, "center")),
    "U-WEAK-FULL": ("Weak · Cold-Start", (-10, -16, "right")),
    "CW-WEAK-WARM": ("Weak · Warm-Start", (-10, 12, "right")),
    "DT-WEAK-COLD": ("Transfer IT · Cold", (10, 6, "left")),
    "DT-WEAK-WARM": ("Transfer IT · Warm", (-10, -16, "right")),
}


def plot_tokens_vs_score(report: dict, output_dir: str) -> None:
    """Scatter: Token-Verbrauch vs. Qualität pro Konfiguration, Farbe = Tier."""
    pass_data = report.get("pass_at_1", {})
    if not pass_data:
        return

    fig, ax = plt.subplots(figsize=(10, 6.2))

    for cid, stats in sorted(pass_data.items()):
        tokens = stats.get("tokens_mean", 0)
        score = stats.get("mean_score", 0)
        if tokens == 0:
            continue
        label, (dx, dy, ha) = TOKENS_LABELS.get(cid, (cid, (8, 6, "left")))
        ax.scatter(tokens, score, color=_pareto_tier_color(cid), s=150,
                   edgecolors="black", linewidth=0.8, zorder=5, alpha=0.9)
        ax.annotate(label, (tokens, score), textcoords="offset points",
                    xytext=(dx, dy), ha=ha, fontsize=9)

    ax.xaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"{v / 1e6:.1f} Mio.")
    )

    from matplotlib.lines import Line2D
    tier_handles = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#4878CF",
               markersize=10, label="Weak (Gemini 2.0)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#E8822A",
               markersize=10, label="Medium (Gemini 2.5)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#6AB162",
               markersize=10, label="Strong (Gemini 3.5)"),
    ]
    ax.legend(handles=tier_handles, fontsize=9, loc="lower right",
              frameon=True, framealpha=0.9)

    ax.set_xlabel("Token-Verbrauch pro Benchmark-Run — weiter links = günstiger",
                  fontsize=11)
    ax.set_ylabel("Mittlerer Score — weiter oben = besser", fontsize=11)
    ax.set_title("Token-Verbrauch vs. Qualität pro Konfiguration", fontsize=13)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax.grid(alpha=0.3)
    sns.despine()
    fig.tight_layout()

    _savefig(fig, output_dir, "06_tokens_vs_score")


def plot_evolution_effect_by_level(report: dict, output_dir: str) -> None:
    """Fokus-Plot für RQ1: pro Modell ein Panel, Evolution AN vs. AUS je Level.

    Statt alle Konfigurationen in einen überladenen Plot zu legen, zeigt diese
    Grafik nur den isolierten Evolutions-Effekt und macht sichtbar, dass die
    Lücke zwischen AN und AUS auf den schwierigen Stufen am größten ist.
    """
    ablation = report.get("evolution_ablation", [])
    if isinstance(ablation, dict):
        ablation = list(ablation.values())
    valid = [r for r in ablation if "error" not in r]
    if not valid:
        return

    pass_data = report.get("pass_at_1", {})

    fig, axes = plt.subplots(1, len(valid), figsize=(5.5 * len(valid), 4.6),
                             sharey=True)
    if len(valid) == 1:
        axes = [axes]

    for ax, r in zip(axes, valid):
        on_id, off_id = r["pair"][0], r["pair"][1]
        on_levels = pass_data.get(on_id, {}).get("per_level", {})
        off_levels = pass_data.get(off_id, {}).get("per_level", {})

        levels = sorted(set(on_levels) & set(off_levels))
        if not levels:
            continue
        x = np.arange(len(levels))
        y_on = [on_levels[lv]["pass_at_1"] for lv in levels]
        y_off = [off_levels[lv]["pass_at_1"] for lv in levels]

        ax.fill_between(x, y_off, y_on, color=EVO_ON_COLOR, alpha=0.12, zorder=1)
        ax.plot(x, y_on, "o-", color=EVO_ON_COLOR, linewidth=2.4, markersize=8,
                label="Evolution AN", zorder=3)
        ax.plot(x, y_off, "o--", color=EVO_OFF_COLOR, linewidth=2.4, markersize=8,
                label="Evolution AUS", zorder=2)

        for xi, (a, b) in enumerate(zip(y_on, y_off)):
            ax.text(xi, max(a, b) + 0.03, f"+{(a - b):.0%}",
                    ha="center", va="bottom", fontsize=9,
                    color=EVO_ON_COLOR, fontweight="bold")

        ax.set_xticks(x)
        ax.set_xticklabels(levels, fontsize=10)
        ax.set_xlabel("Komplexitäts-Level", fontsize=11)
        ax.set_title(_tier_model_name(r.get("tier", "?")), fontsize=12,
                     fontweight="bold")
        ax.set_ylim(0, 1.12)
        ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
        ax.grid(axis="y", alpha=0.3)

    axes[0].set_ylabel("Pass@1 (Erfolgsrate)", fontsize=11)

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, fontsize=10, loc="center left",
               bbox_to_anchor=(1.0, 0.5), frameon=False)
    fig.suptitle("Evolutions-Effekt nach Komplexitäts-Level", fontsize=13)
    sns.despine(fig=fig)
    fig.tight_layout(rect=(0, 0, 0.97, 0.96))

    _savefig(fig, output_dir, "05b_evolution_by_level")


COLD_WARM_PAIRS = [
    ("Bau-Domäne", "U-WEAK-FULL", "CW-WEAK-WARM"),
    ("Domänen-Transfer (IT)", "DT-WEAK-COLD", "DT-WEAK-WARM"),
]

COLD_COLOR = "#7F8FA6"
WARM_COLOR = "#2E7D32"


def plot_cold_warm_tokens(report: dict, output_dir: str) -> None:
    """Gruppierte Balken: Token-Verbrauch Cold vs. Warm je Domäne, mit Δ%.

    Macht den eigentlichen RQ2-Effekt sichtbar: Reuse spart dort spürbar
    Tokens, wo der Cold-Start viel bauen muss (Transfer), während die
    Ersparnis in der eingespielten Bau-Domäne im Rauschen bleibt.
    """
    pass_data = report.get("pass_at_1", {})
    pairs = [(lbl, c, w) for lbl, c, w in COLD_WARM_PAIRS
             if c in pass_data and w in pass_data]
    if not pairs:
        return

    fig, ax = plt.subplots(figsize=(9, 5.6))
    width = 0.34
    x = np.arange(len(pairs))

    for gi, (label, cold_id, warm_id) in enumerate(pairs):
        cold, warm = pass_data[cold_id], pass_data[warm_id]
        c_tok = cold.get("tokens_mean", 0) / 1e6
        w_tok = warm.get("tokens_mean", 0) / 1e6
        delta = (w_tok - c_tok) / c_tok if c_tok else 0.0

        b_cold = ax.bar(gi - width / 2, c_tok, width, color=COLD_COLOR,
                        edgecolor="black", linewidth=0.6,
                        label="Cold-Start" if gi == 0 else None)
        b_warm = ax.bar(gi + width / 2, w_tok, width, color=WARM_COLOR,
                        edgecolor="black", linewidth=0.6,
                        label="Warm-Start (Reuse)" if gi == 0 else None)

        for bars, stats in ((b_cold, cold), (b_warm, warm)):
            r = bars[0]
            ax.text(r.get_x() + r.get_width() / 2, r.get_height() / 2,
                    f"Pass@1\n{stats.get('pass_at_1', 0):.0%}",
                    ha="center", va="center", fontsize=9, color="white",
                    fontweight="bold")

        top = max(c_tok, w_tok)
        y = top * 1.06
        ax.plot([gi - width / 2, gi + width / 2], [y, y], color="#333333",
                linewidth=1.2)
        savings = -delta
        col = WARM_COLOR if savings > 0.005 else "#888888"
        arrow = "↓" if savings > 0.005 else "≈"
        ax.text(gi, y * 1.02, f"{arrow} {abs(delta):.1%} Tokens",
                ha="center", va="bottom", fontsize=11, fontweight="bold",
                color=col)

    ax.set_xticks(x)
    ax.set_xticklabels([p[0] for p in pairs], fontsize=11)
    ax.set_ylabel("Tokens pro Benchmark-Run (Mio.) — weniger = günstiger",
                  fontsize=11)
    ax.set_title("Cold-Start vs. Warm-Start: spart Blueprint-Reuse Tokens?",
                 fontsize=13)
    ax.set_ylim(top=ax.get_ylim()[1] * 1.12)
    ax.legend(fontsize=10, loc="upper right", frameon=True, framealpha=0.9)
    ax.grid(axis="y", alpha=0.3)
    sns.despine()
    fig.tight_layout()

    _savefig(fig, output_dir, "07_cold_warm_tokens")


def generate_all_plots(report: dict, output_dir: str) -> None:
    """Generiert alle Plot-Typen."""
    print(f"Plots → {output_dir}/")
    plot_pass_at_1_boxplot(report, output_dir)
    plot_pareto(report, output_dir)
    plot_heatmap(report, output_dir)
    plot_evolution_effect(report, output_dir)
    plot_pass_by_level(report, output_dir)
    plot_evolution_effect_by_level(report, output_dir)
    plot_tokens_vs_score(report, output_dir)
    plot_cold_warm_tokens(report, output_dir)
    print("  8 Plots generiert")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Modellvergleich — Plot-Generierung")
    p.add_argument("--report", required=True,
                   help="Pfad zu statistics.json aus model_comparison.py")
    p.add_argument("--output", required=True,
                   help="Verzeichnis für Plot-Output")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    with open(args.report) as f:
        report = json.load(f)
    generate_all_plots(report, args.output)


if __name__ == "__main__":
    main()
