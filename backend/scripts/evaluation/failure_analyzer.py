"""
Failure-Kategorisierung für Benchmark-Runs.

Analysiert benchmark_task_results aus der DB und kategorisiert Failures:
- Zero-Token (Pipeline-Timeout vor Execution)
- Build-Timeout / Build-Failure (Developer-Team hat nicht rechtzeitig gebaut)
- Execution-Timeout (Polling-Limit erreicht)
- Near-Miss (Score >= 0.70 aber nicht bestanden)
- Fehlerhafte Execution (Error-Feld gesetzt)

Zeigt außerdem Per-Task Pass-Raten über alle Runs und identifiziert
die unzuverlässigsten Tasks.

Usage:
    cd backend && python -m scripts.evaluation.failure_analyzer
    cd backend && python -m scripts.evaluation.failure_analyzer --run-id <id>
    cd backend && python -m scripts.evaluation.failure_analyzer --suite progressive_complexity_30
"""
from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path

# Projekt-Root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.sql.evaluation_models import BenchmarkRun, BenchmarkTaskResult
from app.models.sql.intervention_models import BlockedChallenge


# ── Failure-Kategorien ────────────────────────────────────────────

def categorize_failure(result: BenchmarkTaskResult) -> str:
    """Ordnet ein fehlgeschlagenes Ergebnis einer Kategorie zu."""
    if result.passed:
        return "PASSED"

    status = (result.status or "").lower()

    # Build-Phase Failures
    if status == "build_timeout":
        return "BUILD_TIMEOUT"
    if status == "build_failed":
        return "BUILD_FAILED"

    # Execution Timeout (vom Polling)
    if status == "timeout":
        return "EXEC_TIMEOUT"

    # Zero-Token = Timeout vor Agent-Execution
    if (result.tokens_total or 0) == 0 and status in ("failed", "resolved", "error"):
        return "ZERO_TOKEN"

    # Error mit Traceback
    if result.error:
        return "ERROR"

    # Near-Miss: guter Score aber nicht bestanden
    if (result.score or 0.0) >= 0.70:
        return "NEAR_MISS"

    # Allgemein schlecht
    if (result.score or 0.0) > 0:
        return "LOW_SCORE"

    return "ZERO_SCORE"


# ── DB-Abfragen ──────────────────────────────────────────────────

async def load_results(
    run_id: str | None = None,
    suite: str | None = None,
) -> tuple[list[BenchmarkRun], list[BenchmarkTaskResult]]:
    """Lädt Benchmark-Ergebnisse aus der DB."""
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # Runs laden
        run_q = select(BenchmarkRun).where(BenchmarkRun.status == "completed")
        if run_id:
            run_q = run_q.where(BenchmarkRun.id == run_id)
        if suite:
            run_q = run_q.where(BenchmarkRun.suite == suite)
        run_q = run_q.order_by(BenchmarkRun.started_at.desc())

        runs = (await db.execute(run_q)).scalars().all()
        run_ids = [r.id for r in runs]

        if not run_ids:
            print("Keine abgeschlossenen Runs gefunden.")
            return [], []

        # Task-Results laden
        result_q = (
            select(BenchmarkTaskResult)
            .where(BenchmarkTaskResult.run_id.in_(run_ids))
            .order_by(BenchmarkTaskResult.task_id)
        )
        results = (await db.execute(result_q)).scalars().all()

        # Blocked Challenges laden (für Routing-Info)
        challenge_ids = [r.challenge_id for r in results if r.challenge_id]
        blocked = {}
        if challenge_ids:
            bc_q = select(BlockedChallenge).where(
                BlockedChallenge.execution_id.in_(challenge_ids)
            )
            bcs = (await db.execute(bc_q)).scalars().all()
            for bc in bcs:
                blocked[bc.execution_id] = bc

    await engine.dispose()
    return runs, results


# ── Analyse-Funktionen ───────────────────────────────────────────

def print_header(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def analyze_runs_overview(runs: list[BenchmarkRun]):
    """Übersicht aller Runs."""
    print_header("RUNS ÜBERSICHT")
    print(f"{'Run-ID':<38} {'Suite':<30} {'Pass@1':>7} {'Tasks':>6} {'Datum'}")
    print("-" * 100)
    for r in runs:
        date_str = r.started_at.strftime("%d.%m.%Y %H:%M") if r.started_at else "?"
        p1 = f"{(r.pass_at_1 or 0)*100:.0f}%"
        mode = f" ({r.ablation_mode})" if r.ablation_mode else ""
        print(f"{r.id:<38} {r.suite}{mode:<30} {p1:>7} {r.tasks_total:>6} {date_str}")


def analyze_failure_categories(results: list[BenchmarkTaskResult]):
    """Breakdown nach Failure-Kategorie."""
    print_header("FAILURE-KATEGORIEN")

    categories: dict[str, list[BenchmarkTaskResult]] = defaultdict(list)
    for r in results:
        cat = categorize_failure(r)
        categories[cat].append(r)

    total = len(results)
    # Sortierung: PASSED zuerst, dann nach Häufigkeit
    order = ["PASSED", "NEAR_MISS", "LOW_SCORE", "ZERO_SCORE", "ZERO_TOKEN",
             "EXEC_TIMEOUT", "BUILD_TIMEOUT", "BUILD_FAILED", "ERROR"]

    print(f"\n{'Kategorie':<18} {'Anzahl':>7} {'Anteil':>8}  Beschreibung")
    print("-" * 80)

    descriptions = {
        "PASSED": "Bestanden",
        "NEAR_MISS": "Score >= 0.70 aber nicht alle Claims gefunden",
        "LOW_SCORE": "Score > 0 aber < 0.70",
        "ZERO_SCORE": "Score = 0, Output vorhanden aber komplett falsch",
        "ZERO_TOKEN": "0 Tokens produziert (Pipeline-Timeout vor Execution)",
        "EXEC_TIMEOUT": "Execution-Timeout (Polling-Limit erreicht)",
        "BUILD_TIMEOUT": "Developer-Team Build hat zu lange gedauert",
        "BUILD_FAILED": "Developer-Team Build fehlgeschlagen",
        "ERROR": "Exception/Error während Execution",
    }

    for cat in order:
        items = categories.get(cat, [])
        if not items:
            continue
        pct = len(items) / total * 100
        desc = descriptions.get(cat, "")
        marker = " ◀ HAUPTPROBLEM" if cat not in ("PASSED",) and len(items) == max(
            len(v) for k, v in categories.items() if k != "PASSED"
        ) else ""
        print(f"{cat:<18} {len(items):>7} {pct:>7.1f}%  {desc}{marker}")

    # Near-Miss Details
    near_misses = categories.get("NEAR_MISS", [])
    if near_misses:
        print(f"\n  Near-Miss Details ({len(near_misses)} Tasks):")
        for r in sorted(near_misses, key=lambda x: x.score or 0, reverse=True):
            missing = r.missing_keywords or []
            miss_str = ", ".join(missing[:3])
            if len(missing) > 3:
                miss_str += f" (+{len(missing)-3})"
            print(f"    {r.task_id:<40} Score: {r.score:.2f}  Fehlend: {miss_str}")


def analyze_per_task_reliability(results: list[BenchmarkTaskResult]):
    """Per-Task Pass-Rate über alle Runs."""
    print_header("PER-TASK ZUVERLÄSSIGKEIT")

    task_stats: dict[str, dict] = defaultdict(lambda: {
        "total": 0, "passed": 0, "scores": [], "categories": defaultdict(int),
        "level": "",
    })

    for r in results:
        tid = r.task_id
        task_stats[tid]["total"] += 1
        task_stats[tid]["level"] = r.level or ""
        task_stats[tid]["scores"].append(r.score or 0.0)
        cat = categorize_failure(r)
        task_stats[tid]["categories"][cat] += 1
        if r.passed:
            task_stats[tid]["passed"] += 1

    # Sortieren nach Pass-Rate aufsteigend (schlechteste zuerst)
    sorted_tasks = sorted(
        task_stats.items(),
        key=lambda x: (x[1]["passed"] / max(x[1]["total"], 1), x[1]["level"]),
    )

    print(f"\n{'Task':<45} {'Level':<5} {'Pass-Rate':>10} {'Avg Score':>10} {'Runs':>5}  Failure-Typen")
    print("-" * 120)

    for tid, stats in sorted_tasks:
        rate = stats["passed"] / max(stats["total"], 1)
        avg_score = sum(stats["scores"]) / max(len(stats["scores"]), 1)
        cats = {k: v for k, v in stats["categories"].items() if k != "PASSED"}
        cat_str = ", ".join(f"{k}:{v}" for k, v in sorted(cats.items(), key=lambda x: -x[1]))

        # Farbmarkierung
        marker = ""
        if rate < 0.25:
            marker = " ⚠️"
        elif rate >= 0.75:
            marker = " ✓"

        print(f"{tid:<45} {stats['level']:<5} {rate*100:>9.0f}% {avg_score:>9.2f} {stats['total']:>5}  {cat_str}{marker}")


def analyze_level_breakdown(results: list[BenchmarkTaskResult]):
    """Aggregierte Statistiken pro Level."""
    print_header("LEVEL-BREAKDOWN")

    level_stats: dict[str, dict] = defaultdict(lambda: {
        "total": 0, "passed": 0, "scores": [],
        "durations": [], "tokens": [],
    })

    for r in results:
        lvl = r.level or "?"
        level_stats[lvl]["total"] += 1
        level_stats[lvl]["scores"].append(r.score or 0.0)
        level_stats[lvl]["durations"].append(r.duration_ms or 0)
        level_stats[lvl]["tokens"].append(r.tokens_total or 0)
        if r.passed:
            level_stats[lvl]["passed"] += 1

    print(f"\n{'Level':<8} {'Pass-Rate':>10} {'Avg Score':>10} {'Avg Duration':>13} {'Avg Tokens':>12} {'n':>5}")
    print("-" * 65)

    for lvl in sorted(level_stats.keys()):
        s = level_stats[lvl]
        rate = s["passed"] / max(s["total"], 1)
        avg_score = sum(s["scores"]) / max(len(s["scores"]), 1)
        avg_dur = sum(s["durations"]) / max(len(s["durations"]), 1) / 1000
        avg_tok = sum(s["tokens"]) / max(len(s["tokens"]), 1)
        print(f"{lvl:<8} {rate*100:>9.0f}% {avg_score:>9.2f} {avg_dur:>11.1f}s {avg_tok:>11.0f} {s['total']:>5}")


def analyze_timing_distribution(results: list[BenchmarkTaskResult]):
    """Zeigt Timing-Verteilung um Timeout-Probleme zu identifizieren."""
    print_header("TIMING-VERTEILUNG")

    durations = [(r.task_id, r.duration_ms or 0, r.status, r.passed) for r in results]
    durations.sort(key=lambda x: -x[1])

    # Buckets
    buckets = {"<30s": 0, "30-60s": 0, "60-120s": 0, "120-300s": 0, ">300s": 0}
    for _, d, _, _ in durations:
        d_s = d / 1000
        if d_s < 30:
            buckets["<30s"] += 1
        elif d_s < 60:
            buckets["30-60s"] += 1
        elif d_s < 120:
            buckets["60-120s"] += 1
        elif d_s < 300:
            buckets["120-300s"] += 1
        else:
            buckets[">300s"] += 1

    print("\nDuration-Verteilung:")
    total = len(durations)
    for bucket, count in buckets.items():
        bar = "█" * int(count / max(total, 1) * 40)
        print(f"  {bucket:<10} {count:>5} ({count/max(total,1)*100:>5.1f}%)  {bar}")

    # Langsamste Tasks
    print(f"\nTop 10 langsamste Tasks:")
    print(f"{'Task':<45} {'Duration':>10} {'Status':<15} {'Passed'}")
    print("-" * 80)
    for tid, d, status, passed in durations[:10]:
        print(f"{tid:<45} {d/1000:>9.1f}s {status or '?':<15} {'✓' if passed else '✗'}")


def analyze_error_messages(results: list[BenchmarkTaskResult]):
    """Gruppiert Error-Messages um häufige Fehler zu finden."""
    errors = [(r.task_id, r.error) for r in results if r.error]
    if not errors:
        return

    print_header("HÄUFIGE FEHLER")

    # Fehler nach erstem Satz gruppieren
    error_groups: dict[str, list[str]] = defaultdict(list)
    for tid, err in errors:
        # Erste Zeile als Schlüssel
        key = err.split("\n")[0][:100]
        error_groups[key].append(tid)

    sorted_groups = sorted(error_groups.items(), key=lambda x: -len(x[1]))
    for msg, tasks in sorted_groups[:10]:
        print(f"\n  [{len(tasks)}x] {msg}")
        for t in tasks[:5]:
            print(f"       → {t}")
        if len(tasks) > 5:
            print(f"       ... und {len(tasks)-5} weitere")


def analyze_missing_claims(results: list[BenchmarkTaskResult]):
    """Häufigste fehlende Claims über alle Runs."""
    print_header("HÄUFIGSTE FEHLENDE CLAIMS")

    claim_counts: dict[str, int] = defaultdict(int)
    claim_tasks: dict[str, set] = defaultdict(set)

    for r in results:
        if not r.passed and r.missing_keywords:
            for claim in r.missing_keywords:
                claim_counts[claim] += 1
                claim_tasks[claim].add(r.task_id)

    if not claim_counts:
        print("  Keine fehlenden Claims gefunden (oder nur Keyword-Evaluation).")
        return

    sorted_claims = sorted(claim_counts.items(), key=lambda x: -x[1])
    print(f"\n{'Claim':<60} {'Fehlend':>8} {'Tasks':>6}")
    print("-" * 80)
    for claim, count in sorted_claims[:20]:
        n_tasks = len(claim_tasks[claim])
        print(f"{claim[:60]:<60} {count:>8} {n_tasks:>6}")


# ── Main ─────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Benchmark Failure-Analyse")
    parser.add_argument("--run-id", help="Nur einen bestimmten Run analysieren")
    parser.add_argument("--suite", help="Nur Runs einer bestimmten Suite")
    parser.add_argument("--last", type=int, default=None, help="Nur die letzten N Runs")
    args = parser.parse_args()

    runs, results = await load_results(run_id=args.run_id, suite=args.suite)

    if not results:
        print("Keine Ergebnisse gefunden.")
        return

    if args.last:
        run_ids = {r.id for r in runs[:args.last]}
        results = [r for r in results if r.run_id in run_ids]
        runs = runs[:args.last]

    print(f"\nAnalyse von {len(results)} Task-Ergebnissen aus {len(runs)} Runs")

    analyze_runs_overview(runs)
    analyze_failure_categories(results)
    analyze_per_task_reliability(results)
    analyze_level_breakdown(results)
    analyze_timing_distribution(results)
    analyze_error_messages(results)
    analyze_missing_claims(results)

    # Zusammenfassung
    print_header("ZUSAMMENFASSUNG")
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    zero_tok = sum(1 for r in results if (r.tokens_total or 0) == 0 and not r.passed)
    near = sum(1 for r in results if not r.passed and (r.score or 0) >= 0.70)
    timeouts = sum(1 for r in results if (r.status or "") in ("timeout", "build_timeout"))

    print(f"  Gesamt:       {total} Task-Ergebnisse")
    print(f"  Bestanden:    {passed} ({passed/total*100:.1f}%)")
    print(f"  Zero-Token:   {zero_tok} ({zero_tok/total*100:.1f}%) — Pipeline-Timeout")
    print(f"  Near-Miss:    {near} ({near/total*100:.1f}%) — Score >= 0.70, fehlende Claims")
    print(f"  Timeouts:     {timeouts} ({timeouts/total*100:.1f}%) — Exec/Build-Timeout")
    print(f"\n  Empfehlung:")
    if zero_tok / total > 0.15:
        print(f"    ★ Zero-Token ist {zero_tok/total*100:.0f}% — Timeout erhöhen oder Pipeline-Engpass finden")
    if near / total > 0.10:
        print(f"    ★ Near-Miss ist {near/total*100:.0f}% — Claim-Evaluation oder Agent-Prompts prüfen")
    if timeouts / total > 0.10:
        print(f"    ★ Timeouts sind {timeouts/total*100:.0f}% — Timeout-Budget pro Phase aufteilen")


if __name__ == "__main__":
    asyncio.run(main())
