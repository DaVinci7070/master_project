from __future__ import annotations

import argparse
import os
import subprocess
import sys

MODES: dict[str, dict[str, str]] = {
    "baseline": {
        "AUTONOMOUS_EVOLUTION_ENABLED": "false",
        "SKILL_REUSE_ENABLED": "false",
        "SHARED_MEMORY_ENABLED": "false",
    },
    "no_memory": {
        "AUTONOMOUS_EVOLUTION_ENABLED": "true",
        "SKILL_REUSE_ENABLED": "true",
        "SHARED_MEMORY_ENABLED": "false",
    },
    "full": {
        "AUTONOMOUS_EVOLUTION_ENABLED": "true",
        "SKILL_REUSE_ENABLED": "true",
        "SHARED_MEMORY_ENABLED": "true",
    },
}


def list_modes():
    print("Available ablation modes:\n")
    for name, flags in MODES.items():
        flag_str = ", ".join(f"{k}={v}" for k, v in flags.items())
        print(f"  {name:12s} — {flag_str}")


def run_ablation(args: argparse.Namespace):
    mode = args.mode
    if mode not in MODES:
        print(f"Error: unknown mode '{mode}'. Available: {', '.join(MODES)}")
        sys.exit(1)

    flags = MODES[mode]

    if args.dry_run:
        print(f"Mode: {mode}")
        print("ENV vars that would be set:")
        for k, v in flags.items():
            print(f"  {k}={v}")
        return

    runner_cmd = [
        sys.executable, "-m", "scripts.evaluation.benchmark_runner",
        "--suite", args.suite,
        "--output", args.output,
        "--seed", str(args.seed),
        "--timeout", str(args.timeout),
        "--poll-interval", str(args.poll_interval),
        "--project-id", args.project_id,
    ]
    if args.csv:
        runner_cmd.extend(["--csv", args.csv])

    env = {**os.environ, **flags}

    print(f"Ablation mode: {mode}")
    for k, v in flags.items():
        print(f"  {k}={v}")
    print(f"Running: {' '.join(runner_cmd)}\n")

    result = subprocess.run(runner_cmd, env=env, cwd=os.getcwd())
    sys.exit(result.returncode)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ablation Mode Switch for Evaluation")
    parser.add_argument("--list", action="store_true", help="List available modes")
    parser.add_argument("--mode", choices=list(MODES.keys()), help="Ablation mode to apply")
    parser.add_argument("--suite", default="dummy_smoke_test", help="YAML suite name")
    parser.add_argument("--output", default="results/ablation_run.json", help="JSON output path")
    parser.add_argument("--csv", default=None, help="CSV output path")
    parser.add_argument("--seed", type=int, default=1, help="Random seed")
    parser.add_argument("--timeout", type=int, default=300, help="Max seconds per task")
    parser.add_argument("--poll-interval", type=int, default=5, help="Poll interval seconds")
    parser.add_argument("--project-id", default="evaluation", help="Project ID")
    parser.add_argument("--dry-run", action="store_true", help="Show flags without running")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None):
    args = parse_args(argv)

    if args.list:
        list_modes()
        return

    if not args.mode:
        print("Error: --mode required (or use --list)")
        sys.exit(1)

    run_ablation(args)


if __name__ == "__main__":
    main()
