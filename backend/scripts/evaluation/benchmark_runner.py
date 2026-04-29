"""
F12 — Evaluation Benchmark Runner.

CLI tool that loads YAML task suites, executes them via the Challenge API,
evaluates Pass@1 with keyword/section matching, and exports JSON + CSV results.

Usage:
    python -m scripts.evaluation.benchmark_runner \
        --suite dummy_smoke_test \
        --output results/run.json \
        --base-url http://localhost:8000/api/v1
"""
from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import argparse
import asyncio
import csv
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import yaml
from pydantic import BaseModel

# Add parent to path for app imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.core.llm_client import LLMClient

log = logging.getLogger(__name__)

DATASETS_DIR = Path(__file__).parent / "datasets"


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------

def load_suite(name: str) -> dict:
    path = DATASETS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Suite not found: {path}")
    with open(path) as f:
        suite = yaml.safe_load(f)
    if "tasks" not in suite or not suite["tasks"]:
        raise ValueError(f"Suite '{name}' has no tasks")
    for task in suite["tasks"]:
        for field in ("task_id", "level", "description", "ground_truth"):
            if field not in task:
                raise ValueError(f"Task missing required field '{field}': {task.get('task_id', '?')}")
        gt = task["ground_truth"]
        # Accept either claim-based or keyword-based ground truth
        has_claims = "required_claims" in gt
        has_keywords = "required_keywords" in gt and "required_sections" in gt
        if not has_claims and not has_keywords:
            raise ValueError(f"ground_truth must have 'required_claims' or 'required_keywords'+'required_sections' for task {task['task_id']}")
    return suite


# ---------------------------------------------------------------------------
# German text normalization & fuzzy matching
# ---------------------------------------------------------------------------

_GERMAN_CHAR_MAP = str.maketrans({
    'ß': 'ss',
    'ä': 'ae', 'Ä': 'Ae',
    'ö': 'oe', 'Ö': 'Oe',
    'ü': 'ue', 'Ü': 'Ue',
})

FUZZY_THRESHOLD = 0.85


def _normalize_german(text: str) -> str:
    """Normalize German special characters and lowercase."""
    return text.translate(_GERMAN_CHAR_MAP).lower()


def _fuzzy_contains(needle: str, haystack: str, threshold: float = FUZZY_THRESHOLD) -> bool:
    """Check if *needle* appears in *haystack* using normalization + fuzzy fallback.

    1. Normalized substring match (handles ß/ä/ö/ü variants).
    2. Fuzzy token match via SequenceMatcher (handles morphological variants
       like plurals, e.g. Nachtrag → Nachträge).
    """
    norm_needle = _normalize_german(needle)
    norm_haystack = _normalize_german(haystack)

    # Fast path: exact normalized substring
    if norm_needle in norm_haystack:
        return True

    # Fuzzy fallback: compare against tokens of similar length
    needle_len = len(norm_needle)
    min_len = max(1, int(needle_len * 0.6))
    max_len = int(needle_len * 1.5)

    for token in set(re.findall(r'\w+', norm_haystack)):
        if min_len <= len(token) <= max_len:
            if SequenceMatcher(None, norm_needle, token).ratio() >= threshold:
                return True

    return False


# ---------------------------------------------------------------------------
# Text extraction from nested execution results
# ---------------------------------------------------------------------------

def _extract_text_from_results(data: Any) -> str:
    """Recursively extract all string values from nested execution results."""
    texts: list[str] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, str) and len(obj) > 3:
            texts.append(obj)
        elif isinstance(obj, dict):
            for value in obj.values():
                _walk(value)
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                _walk(item)

    _walk(data)
    return "\n".join(texts)


# ---------------------------------------------------------------------------
# Pass@1 evaluation (legacy keyword matching)
# ---------------------------------------------------------------------------

def evaluate_pass(output_text: str, ground_truth: dict) -> tuple[bool, list[str], list[str], float]:
    """Check keywords and sections against execution output.

    Uses German normalization and fuzzy matching.
    Returns (pass, missing_kw, missing_sec, score).
    """
    missing_keywords = [
        kw for kw in ground_truth["required_keywords"]
        if not _fuzzy_contains(str(kw), output_text)
    ]
    missing_sections = [
        sec for sec in ground_truth["required_sections"]
        if not _fuzzy_contains(str(sec), output_text)
    ]

    total = len(ground_truth["required_keywords"]) + len(ground_truth["required_sections"])
    matched = total - len(missing_keywords) - len(missing_sections)
    score = round(matched / total, 3) if total else 1.0

    passed = len(missing_keywords) == 0 and len(missing_sections) == 0
    return passed, missing_keywords, missing_sections, score


# ---------------------------------------------------------------------------
# Claim-based evaluation (LLM-as-Judge, FActScore-inspired)
# ---------------------------------------------------------------------------

class ClaimVerdict(BaseModel):
    claim: str
    found: bool
    evidence: str = ""


class ClaimEvaluation(BaseModel):
    verdicts: list[ClaimVerdict]


JUDGE_SYSTEM_PROMPT = """Du bist ein toleranter Evaluator für Baustellenberichte.
Prüfe ob jede genannte Aussage (Claim) inhaltlich im Bericht enthalten ist.

Eine Aussage gilt als "found" wenn die Kern-Information semantisch vorhanden ist,
auch bei:
- Umformulierungen: "Helmpflicht" = "Schutzhelm tragen" = "PSA-Pflicht inkl. Helm"
- Einheiten-Umrechnung: "5000 kg" = "5 Tonnen" = "5t"
- Datumsformate: "11.04.2026" = "11. April 2026" = "2026-04-11"
- Synonyme: "Innenrüttler" = "Rüttelflasche" = "Vibrator", "Gerüst" = "Arbeitsgerüst"
- Implizite Information: Wenn der Bericht "PSA-Kontrolle durch Ing. Weber" sagt,
  dann sind sowohl "Sicherheitsingenieur Weber" als auch "PSA" abgedeckt
- Leichte Abweichungen bei Namen: "Mueller" = "Müller", "Hoffmann" = "Hofmann"

Nur als "not found" bewerten wenn die Information wirklich komplett fehlt.
Im Zweifel für "found" entscheiden.
Antworte NUR mit dem geforderten JSON-Format."""


def _keyword_fallback(output_text: str, claims: list[str]) -> tuple[bool, list[str], float]:
    """Fallback when LLM judge fails: extract key terms from claims and check presence."""
    missing = []
    for claim in claims:
        # Extract significant words (capitalized or long) from claim
        words = [w for w in claim.split() if (len(w) > 3 and w[0].isupper()) or len(w) > 5]
        if not words or not any(_fuzzy_contains(w, output_text) for w in words):
            missing.append(claim)
    total = len(claims)
    found = total - len(missing)
    score = round(found / total, 3) if total else 1.0
    return score >= CLAIM_PASS_THRESHOLD, missing, score


# Schwelle ab der ein Task als "bestanden" gilt (0.85 = 85% der Claims müssen gefunden werden)
CLAIM_PASS_THRESHOLD = 0.85


async def evaluate_claims(
    output_text: str,
    claims: list[str],
    llm_client: LLMClient,
    pass_threshold: float = CLAIM_PASS_THRESHOLD,
) -> tuple[bool, list[str], float]:
    """Evaluate claims via LLM-as-Judge.

    Returns (pass, missing_claims, score).
    Pass wenn score >= pass_threshold (default 85%).
    """
    prompt = f"""Prüfe ob der folgende Bericht diese Aussagen inhaltlich abdeckt.
Sei TOLERANT: Umformulierungen, Synonyme, Einheiten-Umrechnungen und implizite
Informationen zählen als "found". Nur wenn die Information wirklich komplett
fehlt, bewerte als "not found".

BERICHT:
{output_text[:8000]}

CLAIMS:
{json.dumps(claims, ensure_ascii=False, indent=2)}

Für jede Aussage: "found"=true wenn die Information enthalten ist (auch umformuliert,
als Synonym, in anderer Einheit, oder implizit ableitbar).
"found"=false NUR wenn die Information komplett fehlt.
Gib ein kurzes Zitat als "evidence" wenn gefunden."""

    try:
        response = await llm_client.chat_structured(
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_model=ClaimEvaluation,
            temperature=0.0,
            max_tokens=2048,
        )

        missing = [v.claim for v in response.verdicts if not v.found]
        total = len(claims)
        found = total - len(missing)
        score = round(found / total, 3) if total else 1.0
        passed = score >= pass_threshold

        return passed, missing, score

    except Exception as e:
        log.error(f"Claim evaluation failed: {type(e).__name__}: {e}")
        print(f"  [WARN] LLM judge failed: {e} — falling back to keyword match")
        return _keyword_fallback(output_text, claims)


# ---------------------------------------------------------------------------
# Single-task execution
# ---------------------------------------------------------------------------

async def run_task(
    client: httpx.AsyncClient,
    base_url: str,
    task: dict,
    project_id: str,
    timeout: int,
    poll_interval: int,
    llm_client: LLMClient | None = None,
) -> dict:
    """Execute one task through the Challenge API and return a result dict."""
    task_id = task["task_id"]
    execution_id = str(uuid4())
    started_at = datetime.now(timezone.utc)
    result: dict = {
        "task_id": task_id,
        "level": task["level"],
        "challenge_id": None,
        "execution_id": execution_id,
        "status": "pending",
        "pass": False,
        "score": 0.0,
        "duration_ms": 0,
        "agents_executed": 0,
        "tokens_total": 0,
        "missing_keywords": [],
        "missing_sections": [],
        "started_at": started_at.isoformat(),
        "completed_at": None,
        "error": None,
    }

    try:
        # 1. Analyze
        t_analyze = time.monotonic()
        resp = await client.post(
            f"{base_url}/challenges/analyze",
            json={
                "challenge_text": task["description"],
                "execution_id": execution_id,
                "project_id": project_id,
            },
            timeout=60,
        )
        resp.raise_for_status()
        analysis = resp.json()
        analyze_ms = int((time.monotonic() - t_analyze) * 1000)
        challenge_id = analysis["challenge_id"]
        result["challenge_id"] = challenge_id
        route_decision = analysis.get("route_decision", "execute")
        print(f"\n    [{task_id}] Phase 1 ANALYZE: {analyze_ms}ms → route={route_decision}")

        # 2. If developer_team route: approve build plan and wait for capabilities
        t_build = time.monotonic()
        if route_decision == "developer_team" and analysis.get("build_plan"):
            build_status = analysis.get("build_plan_status", "pending")
            auto_apply = analysis.get("auto_apply_enabled", False)

            # Approve the build plan if not auto-applied
            if not auto_apply and build_status == "pending":
                print(f"\n    [BUILD] Approving build plan for {task_id}...")
                resp = await client.post(
                    f"{base_url}/challenges/{challenge_id}/build-plan/approve",
                    json={"approved": True},
                    timeout=60,
                )
                resp.raise_for_status()

            # Poll until build is complete
            build_elapsed = 0.0
            build_timeout = timeout * 0.6  # Use up to 60% of timeout for building
            while build_elapsed < build_timeout:
                await asyncio.sleep(poll_interval)
                build_elapsed += poll_interval

                resp = await client.get(
                    f"{base_url}/challenges/{challenge_id}",
                    timeout=30,
                )
                resp.raise_for_status()
                status_data = resp.json()
                status = status_data["status"]

                if status in ("ready", "partially_ready"):
                    build_ms = int((time.monotonic() - t_build) * 1000)
                    print(f"\n    [{task_id}] Phase 2 BUILD: {build_ms}ms ({build_elapsed:.0f}s polling)")
                    break
                elif status == "build_failed":
                    print(f"\n    [BUILD] Build failed ({build_elapsed:.0f}s)")
                    result["status"] = "build_failed"
                    result["duration_ms"] = int(build_elapsed * 1000)
                    result["completed_at"] = datetime.now(timezone.utc).isoformat()
                    return result
            else:
                print(f"\n    [BUILD] Build timeout ({build_timeout:.0f}s)")
                result["status"] = "build_timeout"
                result["duration_ms"] = int(build_elapsed * 1000)
                result["completed_at"] = datetime.now(timezone.utc).isoformat()
                return result

        # 3. Execute
        t_exec = time.monotonic()
        resp = await client.post(
            f"{base_url}/challenges/{challenge_id}/execute",
            timeout=60,
        )
        resp.raise_for_status()

        # 4. Poll until resolved / failed / timeout
        elapsed = 0.0
        while elapsed < timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            resp = await client.get(
                f"{base_url}/challenges/{challenge_id}",
                timeout=30,
            )
            resp.raise_for_status()
            status_data = resp.json()
            status = status_data["status"]

            if status in ("resolved", "failed"):
                break
        else:
            # Timeout
            exec_ms = int((time.monotonic() - t_exec) * 1000)
            print(f"\n    [{task_id}] Phase 3 EXECUTE: TIMEOUT nach {exec_ms}ms")
            result["status"] = "timeout"
            result["duration_ms"] = int(elapsed * 1000)
            result["completed_at"] = datetime.now(timezone.utc).isoformat()
            return result

        exec_ms = int((time.monotonic() - t_exec) * 1000)
        print(f"\n    [{task_id}] Phase 3 EXECUTE: {exec_ms}ms → status={status}")
        result["status"] = status

        # 5. Get results
        resp = await client.get(
            f"{base_url}/challenges/{challenge_id}/results",
            timeout=30,
        )
        resp.raise_for_status()
        results_data = resp.json()

        result["duration_ms"] = results_data.get("duration_ms") or 0
        result["agents_executed"] = results_data.get("agents_executed", 0)

        # Extract token counts from execution_results
        exec_results = results_data.get("execution_results") or {}
        result["tokens_total"] = exec_results.get("tokens_total", 0)
        result["tokens_input"] = exec_results.get("tokens_input", 0)
        result["tokens_output"] = exec_results.get("tokens_output", 0)

        # 6. Evaluate Pass@1
        if status == "resolved":
            output_text = _extract_text_from_results(exec_results)
            gt = task["ground_truth"]

            # DEBUG: Show what the agents actually produced
            print(f"\n{'='*60}")
            print(f"DEBUG {task_id} — output_text length: {len(output_text)} chars")
            print(f"{'='*60}")
            print(output_text[:3000])
            print(f"{'='*60}\n")

            if "required_claims" in gt and llm_client:
                # Claim-based evaluation (LLM-as-Judge)
                passed, missing_claims, score = await evaluate_claims(
                    output_text=output_text,
                    claims=[str(c) for c in gt["required_claims"]],
                    llm_client=llm_client,
                )
                result["pass"] = passed
                result["score"] = score
                result["missing_keywords"] = missing_claims
            else:
                # Legacy keyword matching
                passed, missing_kw, missing_sec, score = evaluate_pass(output_text, gt)
                result["pass"] = passed
                result["score"] = score
                result["missing_keywords"] = missing_kw
                result["missing_sections"] = missing_sec

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    return result


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

async def run_suite(args: argparse.Namespace) -> dict:
    suite = load_suite(args.suite)
    tasks = suite["tasks"]

    if args.dry_run:
        print(f"Suite: {suite.get('suite', args.suite)}")
        print(f"Description: {suite.get('description', '-')}")
        print(f"Tasks: {len(tasks)}")
        for t in tasks:
            gt = t["ground_truth"]
            if "required_claims" in gt:
                print(f"  - {t['task_id']} ({t['level']}) — {len(gt['required_claims'])} claims")
            else:
                kw = len(gt.get("required_keywords", []))
                sec = len(gt.get("required_sections", []))
                print(f"  - {t['task_id']} ({t['level']}) — {kw} keywords, {sec} sections")
        return {}

    # Create LLM client for claim-based evaluation
    llm_client = LLMClient()

    run_id = str(uuid4())
    started_at = datetime.now(timezone.utc)
    task_results = []

    async with httpx.AsyncClient() as client:
        # Enable auto_apply so developer-team builds trigger automatically
        try:
            resp = await client.put(
                f"{args.base_url}/challenges/settings/user",
                json={"auto_apply": True},
                timeout=10,
            )
            resp.raise_for_status()
            print("  Auto-apply enabled for developer-team builds")
        except Exception as e:
            print(f"  [WARN] Could not enable auto_apply: {e}")

        for task in tasks:
            print(f"  Running {task['task_id']} ({task['level']})...", end=" ", flush=True)
            t0 = time.monotonic()
            result = await run_task(
                client, args.base_url, task,
                project_id=args.project_id,
                timeout=args.timeout,
                poll_interval=args.poll_interval,
                llm_client=llm_client,
            )
            elapsed = time.monotonic() - t0
            mark = "PASS" if result["pass"] else "FAIL"
            print(f"{mark} ({elapsed:.1f}s)")
            task_results.append(result)

    completed_at = datetime.now(timezone.utc)
    passed = sum(1 for r in task_results if r["pass"])
    total = len(task_results)

    run_output = {
        "run_id": run_id,
        "suite": suite.get("suite", args.suite),
        "seed": args.seed,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "base_url": args.base_url,
        "total_tasks": total,
        "passed": passed,
        "failed": total - passed,
        "pass_at_1": round(passed / total, 3) if total else 0.0,
        "tasks": task_results,
    }

    # Write JSON
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(run_output, f, indent=2, ensure_ascii=False)
    print(f"\nJSON written to {output_path}")

    # Write CSV
    csv_path = Path(args.csv) if args.csv else output_path.with_suffix(".csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "run_id", "suite", "seed", "task_id", "level", "status",
            "pass", "score", "duration_ms", "agents_executed", "tokens_total",
            "missing_keywords", "missing_sections", "error",
        ])
        for r in task_results:
            writer.writerow([
                run_id, suite.get("suite", args.suite), args.seed,
                r["task_id"], r["level"], r["status"],
                r["pass"], r["score"], r["duration_ms"],
                r["agents_executed"], r["tokens_total"],
                ";".join(r["missing_keywords"]),
                ";".join(r["missing_sections"]),
                r["error"] or "",
            ])
    print(f"CSV  written to {csv_path}")

    # Summary
    print(f"\n{total} tasks: {passed} passed, {total - passed} failed, Pass@1 = {run_output['pass_at_1'] * 100:.1f}%")

    return run_output


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluation Benchmark Runner")
    parser.add_argument("--suite", required=True, help="YAML suite name in datasets/ (without .yaml)")
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1", help="Backend API base URL")
    parser.add_argument("--seed", type=int, default=1, help="Random seed (stored in metadata)")
    parser.add_argument("--output", required=True, help="Path for JSON result file")
    parser.add_argument("--csv", default=None, help="Path for CSV output (default: <output>.csv)")
    parser.add_argument("--timeout", type=int, default=300, help="Max seconds per task")
    parser.add_argument("--poll-interval", type=int, default=5, help="Seconds between status polls")
    parser.add_argument("--project-id", default="evaluation", help="project_id for challenge submissions")
    parser.add_argument("--dry-run", action="store_true", help="Validate suite without executing")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None):
    args = parse_args(argv)
    print(f"Benchmark Runner — suite={args.suite}, seed={args.seed}")
    asyncio.run(run_suite(args))


if __name__ == "__main__":
    main()
