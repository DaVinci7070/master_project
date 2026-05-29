"""
F12 — Evaluation Benchmark Runner.

CLI tool that loads YAML task suites, executes them via the Challenge API,
evaluates Pass@1 with keyword/section matching, and exports JSON + CSV results.

Usage:
    python -m scripts.evaluation.benchmark_runner \
        --suite dummy_smoke_test \
        --output results/run.json \
        --base-url http://localhost:8000/api/v1

    # Modellvergleich (Sprint 2):
    python -m scripts.evaluation.benchmark_runner \
        --suite progressive_complexity \
        --model-config u_medium_l3l5 \
        --levels L3,L4,L5 \
        --judge-model "gemini/gemini-3.5-flash" \
        --seeds 3 --mode cold \
        --output results/modellvergleich/u_medium_l3l5.json
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

import shutil

import httpx
import yaml
from pydantic import BaseModel

# Add parent to path for app imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.core.llm_client import LLMClient

log = logging.getLogger(__name__)

DATASETS_DIR = Path(__file__).parent / "datasets"
UPLOADS_DIR = Path(__file__).parent.parent.parent / "uploads"


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
        "tokens_thinking": 0,
        "cost_usd": 0.0,
        "cot_verification_used": False,
        "self_reflection_triggered": False,
        "self_reflection_correction": 0.0,
        "reflection_tokens_verifier": 0,
        "missing_keywords": [],
        "missing_sections": [],
        "started_at": started_at.isoformat(),
        "completed_at": None,
        "error": None,
    }

    try:
        # 0. Stage data_dir files into uploads/ if specified
        if "data_dir" in task:
            data_dir = DATASETS_DIR.parent / task["data_dir"]
            if data_dir.is_dir():
                # Target: uploads/<target_name>/ → /data/<target_name>/ im Container
                target_subdir = task.get("data_target", Path(task["data_dir"]).name)
                target_dir = UPLOADS_DIR / target_subdir
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                shutil.copytree(data_dir, target_dir)
                staged = len(list(target_dir.glob("*")))
                print(f"\n    [{task_id}] Staged {staged} files to {target_dir}")
            else:
                print(f"\n    [WARN] data_dir not found: {data_dir}")

        # 1. Analyze (oder Upload bei audio_file-Tasks)
        t_analyze = time.monotonic()

        if "audio_file" in task:
            # Audio-Datei per /upload-Endpoint senden
            audio_path = DATASETS_DIR.parent / task["audio_file"]
            if not audio_path.is_file():
                raise FileNotFoundError(f"Audio-Datei nicht gefunden: {audio_path}")
            print(f"\n    [{task_id}] Uploading audio: {audio_path.name} ({audio_path.stat().st_size} bytes)")
            instructions = task.get("instructions", task["description"])
            with open(audio_path, "rb") as af:
                resp = await client.post(
                    f"{base_url}/challenges/upload",
                    files={"file": (audio_path.name, af, "audio/opus")},
                    data={
                        "project_id": project_id,
                        "execution_id": execution_id,
                        "instructions": instructions,
                    },
                    timeout=600,
                )
        else:
            resp = await client.post(
                f"{base_url}/challenges/analyze",
                json={
                    "challenge_text": task["description"],
                    "execution_id": execution_id,
                    "project_id": project_id,
                },
                timeout=300,
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
                    timeout=300,
                )
                resp.raise_for_status()

            # Poll until build is complete
            build_elapsed = 0.0
            build_timeout = timeout * 0.85  # Muss über Backend-Hard-Timeout (240s) liegen
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

        # Phase-Token-Telemetrie (Sprint C)
        result["tokens_assembly"] = exec_results.get("tokens_assembly", 0)
        result["tokens_execution"] = exec_results.get("tokens_execution", 0)
        result["tokens_verification"] = exec_results.get("tokens_verification", 0)
        result["tokens_adapt"] = exec_results.get("tokens_adapt", 0)
        result["tokens_self_healing"] = exec_results.get("tokens_self_healing", 0)

        # Thinking-Tokens (Sprint 2 Modellvergleich)
        result["tokens_thinking"] = exec_results.get("tokens_thinking", 0)

        # Reflexion-Metriken (Sprint 5)
        ref_m = exec_results.get("reflexion_metrics") or {}
        result["cot_verification_used"] = ref_m.get("cot_verification_used", False)
        result["self_reflection_triggered"] = ref_m.get("self_reflection_triggered", False)
        result["self_reflection_correction"] = ref_m.get("self_reflection_correction", 0.0)
        result["reflection_tokens_verifier"] = ref_m.get("reflection_tokens_verifier", 0)

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
# Model-Config + Kosten (Sprint 2)
# ---------------------------------------------------------------------------

async def _apply_model_config(base_url: str, config) -> dict:
    """Setzt Modelle + Ablation per Settings-API und gibt Originalzustand zurück."""
    async with httpx.AsyncClient() as client:
        # Originalzustand holen
        resp = await client.get(f"{base_url}/settings/current", timeout=10)
        resp.raise_for_status()
        original = resp.json()

        # Modelle setzen
        resp = await client.put(
            f"{base_url}/settings/models",
            json={"models": config.models},
            timeout=10,
        )
        resp.raise_for_status()
        print(f"  Modelle gesetzt: {config.primary_model()} (uniform={config.is_uniform()})")

        # Ablation-Flags setzen
        resp = await client.put(
            f"{base_url}/settings/ablation",
            json=config.ablation.model_dump(),
            timeout=10,
        )
        resp.raise_for_status()
        flags = config.ablation
        print(f"  Ablation: evo={flags.autonomous_evolution_enabled}, "
              f"mem={flags.shared_memory_enabled}, reuse={flags.skill_reuse_enabled}")

    return original


async def _restore_settings(base_url: str, original: dict) -> None:
    """Stellt den Originalzustand der Settings wieder her."""
    async with httpx.AsyncClient() as client:
        try:
            await client.put(
                f"{base_url}/settings/models",
                json={"models": original["models"]},
                timeout=10,
            )
            await client.put(
                f"{base_url}/settings/ablation",
                json=original["ablation"],
                timeout=10,
            )
            print("  Settings auf Originalzustand zurückgesetzt")
        except Exception as e:
            print(f"  [WARN] Settings-Restore fehlgeschlagen: {e}")


def _calculate_task_cost(task_result: dict, pricing: dict) -> float:
    """Berechnet USD-Kosten eines Tasks basierend auf Token-Counts und Pricing."""
    input_tokens = task_result.get("tokens_input", 0) or 0
    output_tokens = task_result.get("tokens_output", 0) or 0
    thinking_tokens = task_result.get("tokens_thinking", 0) or 0

    # Text-Output = completion - thinking
    text_tokens = max(0, output_tokens - thinking_tokens)

    cost = (
        (input_tokens / 1_000_000) * pricing.get("input", 0)
        + (text_tokens / 1_000_000) * pricing.get("output", 0)
        + (thinking_tokens / 1_000_000) * pricing.get("thinking", 0)
    )
    return round(cost, 6)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

async def run_suite(args: argparse.Namespace) -> dict:
    suite = load_suite(args.suite)
    tasks = suite["tasks"]

    # ── Model-Config laden (Sprint 2) ────────────────────────────────
    model_config = None
    if args.model_config:
        from scripts.evaluation.model_configs.schema import load_model_config
        model_config = load_model_config(args.model_config)
        print(f"Model-Config: {model_config.config_id} ({model_config.primary_model()})")

        # Levels aus Config übernehmen wenn nicht per CLI gesetzt
        if not args.levels and model_config.levels:
            args.levels = ",".join(model_config.levels)

        # Judge-Modell aus Config übernehmen wenn nicht per CLI gesetzt
        if not args.judge_model and model_config.judge_model:
            args.judge_model = model_config.judge_model

    # ── Level-Filter anwenden ─────────────────────────────────────────
    if args.levels:
        allowed = {l.strip() for l in args.levels.split(",")}
        before = len(tasks)
        tasks = [t for t in tasks if t["level"] in allowed]
        print(f"Level-Filter: {allowed} → {len(tasks)}/{before} Tasks")
        if not tasks:
            raise ValueError(f"Keine Tasks nach Level-Filter {allowed}")
        suite["tasks"] = tasks

    if args.dry_run:
        print(f"Suite: {suite.get('suite', args.suite)}")
        print(f"Description: {suite.get('description', '-')}")
        print(f"Tasks: {len(tasks)}")
        if model_config:
            print(f"Model-Config: {model_config.config_id}")
            print(f"  Models: {model_config.models}")
            print(f"  Ablation: {model_config.ablation.model_dump()}")
        print(f"Judge: {args.judge_model or '(system default)'}")
        for t in tasks:
            gt = t["ground_truth"]
            if "required_claims" in gt:
                print(f"  - {t['task_id']} ({t['level']}) — {len(gt['required_claims'])} claims")
            else:
                kw = len(gt.get("required_keywords", []))
                sec = len(gt.get("required_sections", []))
                print(f"  - {t['task_id']} ({t['level']}) — {kw} keywords, {sec} sections")
        return {}

    # ── Modelle + Ablation per Settings-API setzen ────────────────────
    original_settings: dict | None = None
    if model_config:
        original_settings = await _apply_model_config(args.base_url, model_config)

    # Multi-Seed-Loop: bei seeds==1 Verhalten unverändert, bei n>1 pro Seed
    # eigener Output und am Ende Aggregat-Datei für Wilcoxon-Auswertung.
    seeds = max(1, int(getattr(args, "seeds", 1)))
    base_seed = int(args.seed)
    suite_name = suite.get("suite", args.suite)

    seed_outputs: list[dict] = []
    try:
        for i in range(seeds):
            current_seed = base_seed + i
            seed_args = argparse.Namespace(**vars(args))
            seed_args.seed = current_seed
            seed_args._model_config = model_config

            # Per-Seed-Output-Pfade ableiten — bei seeds==1 unverändert
            if seeds > 1:
                base_out = Path(args.output)
                seed_args.output = str(
                    base_out.with_name(f"{base_out.stem}_seed{current_seed}{base_out.suffix}")
                )
                if args.csv:
                    base_csv = Path(args.csv)
                    seed_args.csv = str(
                        base_csv.with_name(f"{base_csv.stem}_seed{current_seed}{base_csv.suffix}")
                    )
                print(f"\n=== Seed {i + 1}/{seeds} (seed={current_seed}) ===")

                # Cold-Reset zwischen Seeds (nicht vor dem ersten Seed —
                # Annahme: User hat State vor dem Run vorbereitet).
                if args.mode == "cold" and i > 0:
                    print(f"  Cold-Reset vor Seed {current_seed}...")
                    from scripts.evaluation.cold_warm_switch import cold_reset
                    reset_summary = await cold_reset()
                    print(f"  Reset: tables={reset_summary.get('tables_truncated')} "
                          f"qdrant={len(reset_summary.get('qdrant_cleared', []))} "
                          f"agents={reset_summary.get('agents_seeded')}")

            seed_output = await _run_single_seed(seed_args, suite, tasks)
            seed_outputs.append(seed_output)
    finally:
        # Originalzustand wiederherstellen (auch bei Abbruch)
        if original_settings:
            await _restore_settings(args.base_url, original_settings)

    # Aggregat nur wenn n>1
    if seeds > 1:
        _write_aggregate(args, suite_name, seed_outputs)

    # Rückgabe: bei n=1 wie vorher, sonst Aggregat-Repräsentation
    return seed_outputs[0] if seeds == 1 else {
        "suite": suite_name,
        "seeds": seeds,
        "seed_outputs": seed_outputs,
    }


async def _run_single_seed(args, suite: dict, tasks: list[dict]) -> dict:
    """Führt eine einzelne Seed-Iteration aus (Original-Run-Logic)."""
    # Judge-Modell: explizit gesetzt → separater Client, sonst System-Default
    judge_model = getattr(args, "judge_model", None)
    if judge_model:
        llm_client = LLMClient(model=judge_model)
        print(f"  Judge-Modell: {judge_model} (unabhängig vom System-Modell)")
    else:
        llm_client = LLMClient()

    model_config = getattr(args, "_model_config", None)

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

    # Kosten pro Task und aggregiert berechnen
    total_cost = 0.0
    if model_config:
        from scripts.evaluation.model_configs.schema import MODEL_PRICING
        pricing = MODEL_PRICING.get(model_config.primary_model(), {})
        for r in task_results:
            cost = _calculate_task_cost(r, pricing)
            r["cost_usd"] = cost
            total_cost += cost

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
        # Config-Metadaten (Sprint 2)
        "model_config_id": model_config.config_id if model_config else None,
        "models_used": model_config.models if model_config else None,
        "ablation_flags": model_config.ablation.model_dump() if model_config else None,
        "judge_model": judge_model,
        "cost_usd_total": round(total_cost, 6),
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
            "tokens_input", "tokens_output", "tokens_thinking",
            "tokens_assembly", "tokens_execution", "tokens_verification",
            "tokens_adapt", "tokens_self_healing",
            "cost_usd", "model_config_id",
            "missing_keywords", "missing_sections", "error",
            "cot_verification", "self_reflection", "reflection_correction",
            "reflection_tokens",
        ])
        config_id = model_config.config_id if model_config else ""
        for r in task_results:
            writer.writerow([
                run_id, suite.get("suite", args.suite), args.seed,
                r["task_id"], r["level"], r["status"],
                r["pass"], r["score"], r["duration_ms"],
                r["agents_executed"], r["tokens_total"],
                r.get("tokens_input", 0),
                r.get("tokens_output", 0),
                r.get("tokens_thinking", 0),
                r.get("tokens_assembly", 0),
                r.get("tokens_execution", 0),
                r.get("tokens_verification", 0),
                r.get("tokens_adapt", 0),
                r.get("tokens_self_healing", 0),
                r.get("cost_usd", 0.0),
                config_id,
                ";".join(r["missing_keywords"]),
                ";".join(r["missing_sections"]),
                r["error"] or "",
                r.get("cot_verification_used", ""),
                r.get("self_reflection_triggered", ""),
                r.get("self_reflection_correction", ""),
                r.get("reflection_tokens_verifier", ""),
            ])
    print(f"CSV  written to {csv_path}")

    # Summary
    print(f"\n{total} tasks: {passed} passed, {total - passed} failed, Pass@1 = {run_output['pass_at_1'] * 100:.1f}%")
    if total_cost > 0:
        print(f"Kosten: ${total_cost:.4f} ({run_output.get('model_config_id', '-')})")

    return run_output


def _write_aggregate(args, suite_name: str, seed_outputs: list[dict]) -> None:
    """Aggregat-JSON für Wilcoxon-Auswertung schreiben."""
    base_out = Path(args.output)
    aggregate_path = base_out.with_name(f"{base_out.stem}_aggregate{base_out.suffix}")

    pass_at_1_per_seed = [s["pass_at_1"] for s in seed_outputs]
    tokens_per_seed = [
        sum(t.get("tokens_total") or 0 for t in s["tasks"]) for s in seed_outputs
    ]
    duration_per_seed = [
        sum(t.get("duration_ms") or 0 for t in s["tasks"]) for s in seed_outputs
    ]

    # Task-Pass-Matrix: rows=tasks, cols=seeds — Input für Wilcoxon
    task_ids = [t["task_id"] for t in seed_outputs[0]["tasks"]]
    task_pass_matrix: dict[str, list[int]] = {}
    for tid in task_ids:
        row: list[int] = []
        for s in seed_outputs:
            r = next((x for x in s["tasks"] if x["task_id"] == tid), None)
            row.append(1 if (r and r["pass"]) else 0)
        task_pass_matrix[tid] = row

    n = len(pass_at_1_per_seed)
    mean_pass = sum(pass_at_1_per_seed) / n if n else 0.0
    var = sum((x - mean_pass) ** 2 for x in pass_at_1_per_seed) / n if n else 0.0
    std_pass = var ** 0.5

    aggregate = {
        "suite": suite_name,
        "seeds": n,
        "seed_run_ids": [s["run_id"] for s in seed_outputs],
        "pass_at_1_per_seed": pass_at_1_per_seed,
        "pass_at_1_mean": round(mean_pass, 4),
        "pass_at_1_std": round(std_pass, 4),
        "tokens_total_per_seed": tokens_per_seed,
        "duration_ms_per_seed": duration_per_seed,
        "task_pass_matrix": task_pass_matrix,
    }
    aggregate_path.parent.mkdir(parents=True, exist_ok=True)
    with open(aggregate_path, "w") as f:
        json.dump(aggregate, f, indent=2, ensure_ascii=False)
    print(f"\nAggregate JSON written to {aggregate_path}")
    print(f"Pass@1 mean={mean_pass * 100:.1f}% std={std_pass * 100:.1f}% "
          f"(seeds={n})")


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
    parser.add_argument("--timeout", type=int, default=1800, help="Max seconds per task (30min, Audio-Tasks brauchen Skill-Build + Transkription + Multi-Agent-Waves)")
    parser.add_argument("--poll-interval", type=int, default=5, help="Seconds between status polls")
    parser.add_argument("--project-id", default="evaluation", help="project_id for challenge submissions")
    parser.add_argument("--dry-run", action="store_true", help="Validate suite without executing")
    parser.add_argument("--seeds", type=int, default=1,
                        help="Anzahl Seed-Iterationen (n>1 erzeugt Aggregat-JSON)")
    parser.add_argument("--mode", choices=["warm", "cold"], default="warm",
                        help="cold: zwischen Seeds System-State zurücksetzen")
    parser.add_argument("--model-config", default=None,
                        help="Model-Config Name oder Pfad (z.B. 'u_medium_l3l5'). "
                             "Setzt Modelle + Ablation-Flags per Settings-API.")
    parser.add_argument("--judge-model", default=None,
                        help="Festes Judge-Modell für LLM-as-Judge (default: System-Modell). "
                             "Wird aus --model-config übernommen falls dort gesetzt.")
    parser.add_argument("--levels", default=None,
                        help="Komma-separierte Level-Filter (z.B. 'L3,L4,L5'). "
                             "Wird aus --model-config übernommen falls dort gesetzt.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None):
    args = parse_args(argv)
    config_info = f", config={args.model_config}" if args.model_config else ""
    judge_info = f", judge={args.judge_model}" if args.judge_model else ""
    levels_info = f", levels={args.levels}" if args.levels else ""
    print(f"Benchmark Runner — suite={args.suite}, seeds={args.seeds}, "
          f"base_seed={args.seed}, mode={args.mode}{config_info}{judge_info}{levels_info}")
    asyncio.run(run_suite(args))


if __name__ == "__main__":
    main()
