from __future__ import annotations

import argparse
import asyncio
import csv
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

import httpx


async def fetch_json(client: httpx.AsyncClient, url: str) -> dict | None:
    """GET a URL and return parsed JSON, or None on error."""
    try:
        resp = await client.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  Warning: failed to fetch {url}: {e}")
        return None


async def collect_api_metrics(client: httpx.AsyncClient, base_url: str) -> dict:
    """Gather metrics from various backend endpoints."""
    metrics: dict = {
        "blueprint_reuse_rate": None,
        "topology_changes": None,
        "skills_built": None,
        "prompts_evolved": None,
        "evolution_attempts": None,
        "evolution_succeeded": None,
    }

    registry = await fetch_json(client, f"{base_url}/skills/registry/stats")
    if registry and registry.get("skills"):
        skills = registry["skills"]
        reused = sum(1 for s in skills if s.get("executions", 0) > 1)
        total = len(skills)
        metrics["blueprint_reuse_rate"] = round(reused / total, 3) if total else 0.0
    elif registry:
        metrics["blueprint_reuse_rate"] = 0.0

    topo = await fetch_json(client, f"{base_url}/topology/history?limit=100")
    if topo is not None:
        metrics["topology_changes"] = topo.get("total", 0)

    skills_resp = await fetch_json(client, f"{base_url}/skills?limit=100")
    if skills_resp is not None:
        metrics["skills_built"] = skills_resp.get("total", 0)

    evo = await fetch_json(client, f"{base_url}/evolution/stats")
    if evo is not None:
        metrics["evolution_attempts"] = evo.get("total_attempts", 0)
        by_status = evo.get("by_status", {})
        metrics["evolution_succeeded"] = by_status.get("succeeded", 0)
        by_artifact = evo.get("by_artifact_type", {})
        metrics["prompts_evolved"] = by_artifact.get("prompt", 0)

    return metrics


def compute_runner_metrics(run_data: dict) -> dict:
    """Derive latency percentiles and token aggregates from runner output."""
    tasks = run_data.get("tasks", [])
    durations = [t["duration_ms"] for t in tasks if t.get("duration_ms")]
    tokens = [t.get("tokens_total", 0) for t in tasks]

    total_tokens = sum(tokens)
    total_tasks = run_data.get("total_tasks", len(tasks))

    return {
        "pass_at_1": run_data.get("pass_at_1", 0.0),
        "total_tasks": total_tasks,
        "total_tokens": total_tokens,
        "avg_tokens_per_task": round(total_tokens / total_tasks) if total_tasks else 0,
        "p50_latency_ms": round(statistics.median(durations)) if durations else 0,
        "p95_latency_ms": round(percentile(durations, 95)) if durations else 0,
    }


def percentile(data: list[float | int], pct: float) -> float:
    """Compute the pct-th percentile of a sorted list."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * pct / 100.0
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return float(sorted_data[f])
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


async def collect(args: argparse.Namespace) -> dict:
    run_path = Path(args.run_results)
    if not run_path.exists():
        raise FileNotFoundError(f"Run results not found: {run_path}")

    with open(run_path) as f:
        run_data = json.load(f)

    runner_metrics = compute_runner_metrics(run_data)

    async with httpx.AsyncClient() as client:
        api_metrics = await collect_api_metrics(client, args.base_url)

    summary = {
        **runner_metrics,
        **api_metrics,
        "false_negative_rate": None,
        "false_positive_rate": None,
    }

    per_task = [
        {
            "task_id": t["task_id"],
            "level": t["level"],
            "pass": t["pass"],
            "duration_ms": t.get("duration_ms", 0),
            "tokens_total": t.get("tokens_total", 0),
        }
        for t in run_data.get("tasks", [])
    ]

    output = {
        "run_id": run_data.get("run_id", "unknown"),
        "suite": run_data.get("suite", "unknown"),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "per_task": per_task,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Metrics JSON written to {output_path}")

    csv_path = Path(args.csv) if args.csv else output_path.with_suffix(".csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        header = [
            "run_id", "suite", "pass_at_1", "total_tasks", "total_tokens",
            "avg_tokens_per_task", "p50_latency_ms", "p95_latency_ms",
            "blueprint_reuse_rate", "topology_changes", "skills_built",
            "prompts_evolved",
        ]
        writer.writerow(header)
        writer.writerow([
            output["run_id"], output["suite"],
            summary["pass_at_1"], summary["total_tasks"],
            summary["total_tokens"], summary["avg_tokens_per_task"],
            summary["p50_latency_ms"], summary["p95_latency_ms"],
            summary.get("blueprint_reuse_rate", ""),
            summary.get("topology_changes", ""),
            summary.get("skills_built", ""),
            summary.get("prompts_evolved", ""),
        ])
    print(f"Metrics CSV  written to {csv_path}")

    print(f"\nPass@1: {summary['pass_at_1'] * 100:.1f}%  |  "
          f"p50={summary['p50_latency_ms']}ms  p95={summary['p95_latency_ms']}ms  |  "
          f"tokens={summary['total_tokens']}  |  "
          f"reuse={summary.get('blueprint_reuse_rate', 'n/a')}  |  "
          f"evo={summary.get('evolution_attempts', 'n/a')} attempts")

    return output


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluation Metrics Collector")
    parser.add_argument("--run-results", required=True, help="Path to benchmark runner JSON output")
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1", help="Backend API base URL")
    parser.add_argument("--output", required=True, help="Path for metrics JSON output")
    parser.add_argument("--csv", default=None, help="Path for CSV output (default: <output>.csv)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None):
    args = parse_args(argv)
    print(f"Metrics Collector — reading {args.run_results}")
    asyncio.run(collect(args))


if __name__ == "__main__":
    main()
