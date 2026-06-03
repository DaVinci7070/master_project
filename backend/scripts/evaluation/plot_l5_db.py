from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

COLORS = {"cold": "#4878CF", "warm": "#E8822A"}


def plot_skill_vs_task(cold: dict, warm: dict, output_dir: Path) -> None:
    """Plot 1: Skill-Erfolgsrate vs Task-Pass-Rate."""
    fig, ax = plt.subplots(figsize=(7, 4.5))

    labels = ["Cold-Start", "Warm-Start"]
    x = np.arange(len(labels))
    width = 0.32

    pass_rates = [cold["pass_at_1"] * 100, warm["pass_at_1"] * 100]
    tc_total_c = cold["tool_calls_total"]
    tc_ok_c = cold["tool_calls_succeeded"]
    tc_total_w = warm["tool_calls_total"]
    tc_ok_w = warm["tool_calls_succeeded"]
    tool_rates = [
        tc_ok_c / tc_total_c * 100 if tc_total_c else 0,
        tc_ok_w / tc_total_w * 100 if tc_total_w else 0,
    ]

    bars1 = ax.bar(x - width / 2, pass_rates, width, label="Task Pass@1", color="#4878CF")
    bars2 = ax.bar(x + width / 2, tool_rates, width, label="Tool-Call-Erfolgsrate", color="#6AB162")

    for bar, val in zip(bars1, pass_rates):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5,
                f"{val:.0f}%", ha="center", va="bottom", fontsize=11, fontweight="bold")
    for bar, val in zip(bars2, tool_rates):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5,
                f"{val:.0f}%", ha="center", va="bottom", fontsize=11, fontweight="bold")

    ax.set_ylabel("Erfolgsrate (%)")
    ax.set_title("L5 DB-Benchmark: Skill-Qualität vs Task-Erfolg")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 115)
    ax.legend(loc="upper left")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(output_dir / f"11_skill_vs_task_pass.{ext}", dpi=200)
    plt.close(fig)
    print(f"  Plot 1: 11_skill_vs_task_pass")


def plot_per_task_detail(cold: dict, warm: dict, output_dir: Path) -> None:
    """Plot 2: Per-Task Tool-Call Detail."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)

    for ax, data, label, color in [
        (axes[0], cold, "Cold-Start", COLORS["cold"]),
        (axes[1], warm, "Warm-Start", COLORS["warm"]),
    ]:
        tasks = data["tasks"]
        names = [t["task_id"].replace("L5_2_", "") for t in tasks]
        succeeded = [t.get("tool_calls_succeeded", 0) for t in tasks]
        failed = [t.get("tool_calls_failed", 0) for t in tasks]
        passed = [t.get("pass", False) for t in tasks]

        y = np.arange(len(names))
        ax.barh(y, succeeded, height=0.6, label="Succeeded", color="#6AB162")
        ax.barh(y, failed, height=0.6, left=succeeded, label="Failed", color="#D64545")

        for i, p in enumerate(passed):
            marker = "✓" if p else "✗"
            clr = "#6AB162" if p else "#D64545"
            total = succeeded[i] + failed[i]
            ax.text(total + 0.3, i, marker, va="center", fontsize=13, color=clr, fontweight="bold")

        ax.set_yticks(y)
        ax.set_yticklabels(names)
        ax.set_xlabel("Tool-Calls")
        ax.set_title(label)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        if ax == axes[0]:
            ax.legend(loc="lower right", fontsize=9)

    fig.suptitle("L5 DB-Benchmark: Tool-Calls pro Task (✓ = Task bestanden)", fontsize=12)
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(output_dir / f"12_tool_calls_per_task.{ext}", dpi=200)
    plt.close(fig)
    print(f"  Plot 2: 12_tool_calls_per_task")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cold", required=True)
    parser.add_argument("--warm", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    cold = json.load(open(args.cold))
    warm = json.load(open(args.warm))
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    plot_skill_vs_task(cold, warm, output_dir)
    plot_per_task_detail(cold, warm, output_dir)
    print("Done.")


if __name__ == "__main__":
    main()
