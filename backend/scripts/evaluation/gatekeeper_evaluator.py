from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.skills.testing.code_validator import CodeValidatorService, ValidationResult

log = logging.getLogger(__name__)

DATASETS_DIR = Path(__file__).parent / "datasets"

THRESHOLD_SWEEP = [0.5, 0.6, 0.7, 0.8, 0.9]


def load_gatekeeper_suite() -> list[dict]:
    path = DATASETS_DIR / "gatekeeper_skills.yaml"
    with open(path) as f:
        suite = yaml.safe_load(f)
    return suite.get("skills", [])


def compute_metrics(results: list[dict]) -> dict:
    tp = sum(1 for r in results if r["classification"] == "TP")
    tn = sum(1 for r in results if r["classification"] == "TN")
    fp = sum(1 for r in results if r["classification"] == "FP")
    fn = sum(1 for r in results if r["classification"] == "FN")

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    accuracy = (tp + tn) / len(results) if results else 0.0

    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    fnr = fn / (fn + tp) if (fn + tp) > 0 else 0.0

    return {
        "total": len(results),
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "false_positive_rate": round(fpr, 4),
        "false_negative_rate": round(fnr, 4),
    }


def compute_per_category(results: list[dict]) -> dict:
    categories: dict[str, list[dict]] = {}
    for r in results:
        cat = r["category"]
        categories.setdefault(cat, []).append(r)
    return {cat: compute_metrics(items) for cat, items in sorted(categories.items())}


def _classify(expected_block: bool, actually_blocked: bool) -> str:
    if expected_block and actually_blocked:
        return "TP"
    if not expected_block and not actually_blocked:
        return "TN"
    if not expected_block and actually_blocked:
        return "FP"
    return "FN"


def evaluate_skill_ast(
    validator: CodeValidatorService,
    skill: dict,
    ground_truth_field: str = "expected_validation",
) -> dict:
    skill_id = skill["skill_id"]
    code = skill["code"]
    expected = skill.get(ground_truth_field, skill.get("expected_validation", "unknown"))
    expected_block = expected in ("block", "poisoned", "unsafe")

    start = time.monotonic()
    result: ValidationResult = validator.validate(code)
    duration_ms = int((time.monotonic() - start) * 1000)

    actually_blocked = not result.is_valid
    classification = _classify(expected_block, actually_blocked)

    return {
        "skill_id": skill_id,
        "category": skill.get("category", "unknown"),
        "expected": "block" if expected_block else "pass",
        "actual": "blocked" if actually_blocked else "passed",
        "classification": classification,
        "correct": classification in ("TP", "TN"),
        "blocked_constructs": result.blocked_constructs,
        "errors": result.errors,
        "duration_ms": duration_ms,
    }


def run_ast_evaluation(
    skills: list[dict],
    ground_truth_field: str = "expected_validation",
) -> list[dict]:
    validator = CodeValidatorService()
    results = []
    for skill in skills:
        r = evaluate_skill_ast(validator, skill, ground_truth_field=ground_truth_field)
        _print_skill_result(r)
        results.append(r)
    return results


async def evaluate_skill_alignment(
    validator,
    skill: dict,
    threshold: float = 0.7,
) -> dict:
    skill_id = skill["skill_id"]
    description = skill["description"]
    code = skill["code"]
    expected = skill.get("expected_alignment", skill.get("expected_validation", "unknown"))
    expected_block = expected in ("block", "poisoned", "unsafe")

    result = await validator.validate_alignment(description, code, threshold=threshold)
    actually_blocked = not result.is_aligned
    classification = _classify(expected_block, actually_blocked)

    return {
        "skill_id": skill_id,
        "category": skill.get("category", "unknown"),
        "expected": "block" if expected_block else "pass",
        "actual": "blocked" if actually_blocked else "passed",
        "classification": classification,
        "correct": classification in ("TP", "TN"),
        "alignment_score": result.alignment_score,
        "reconstructed_description": result.reconstructed_description,
        "discrepancies": result.discrepancies,
        "missing_functionality": result.missing_functionality,
        "constitution_violations": result.constitution_violations,
        "reasoning": result.reasoning,
        "duration_ms": result.validation_time_ms,
    }


async def run_alignment_evaluation(
    skills: list[dict],
    threshold: float = 0.7,
    quiet: bool = False,
) -> list[dict]:
    from app.skills.testing.code_alignment_validator import CodeAlignmentValidator
    from app.core.llm_client import LLMClient
    from app.core.config import settings

    llm = LLMClient(model=settings.code_alignment_model) if settings.code_alignment_model else LLMClient()
    validator = CodeAlignmentValidator(llm_client=llm, threshold=threshold)

    results = []
    for skill in skills:
        r = await evaluate_skill_alignment(validator, skill, threshold=threshold)
        if not quiet:
            _print_skill_result(r)
        results.append(r)
    return results


def combine_results(
    ast_results: list[dict],
    alignment_results: list[dict],
) -> list[dict]:
    """Blockiert wenn AST ODER Alignment blockt."""
    alignment_map = {r["skill_id"]: r for r in alignment_results}
    combined = []

    for ast_r in ast_results:
        sid = ast_r["skill_id"]
        align_r = alignment_map.get(sid, {})

        ast_blocked = ast_r["actual"] == "blocked"
        align_blocked = align_r.get("actual") == "blocked"
        actually_blocked = ast_blocked or align_blocked

        expected = align_r.get("expected", ast_r["expected"])
        expected_block = expected == "block"
        classification = _classify(expected_block, actually_blocked)

        combined.append({
            "skill_id": sid,
            "category": ast_r["category"],
            "expected": expected,
            "actual": "blocked" if actually_blocked else "passed",
            "classification": classification,
            "correct": classification in ("TP", "TN"),
            "ast_blocked": ast_blocked,
            "alignment_blocked": align_blocked,
            "alignment_score": align_r.get("alignment_score"),
            "duration_ms": ast_r["duration_ms"] + align_r.get("duration_ms", 0),
        })

    return combined


async def run_threshold_sweep(
    skills: list[dict],
    thresholds: list[float] | None = None,
) -> list[dict]:
    thresholds = thresholds or THRESHOLD_SWEEP
    sweep_results = []

    for threshold in thresholds:
        print(f"\n  Threshold={threshold:.1f}...")
        results = await run_alignment_evaluation(skills, threshold=threshold, quiet=True)
        metrics = compute_metrics(results)
        sweep_results.append({
            "threshold": threshold,
            "tpr": metrics["recall"],
            "fpr": metrics["false_positive_rate"],
            "f1": metrics["f1"],
            "precision": metrics["precision"],
            "recall": metrics["recall"],
            "accuracy": metrics["accuracy"],
        })
        print(f"    TPR={metrics['recall']:.3f} FPR={metrics['false_positive_rate']:.3f} F1={metrics['f1']:.3f}")

    return sweep_results


def _print_skill_result(r: dict):
    status = "BLOCKED" if r["actual"] == "blocked" else "PASSED"
    mark = "OK" if r["correct"] else "FEHLER"
    extra = ""
    if "alignment_score" in r and r["alignment_score"] is not None:
        extra = f" score={r['alignment_score']:.2f}"
    print(f"  [{mark}] {r['skill_id']}: {status} "
          f"(erwartet={r['expected']}, class={r['classification']}{extra})")


def _print_layer_summary(name: str, metrics: dict, per_category: dict):
    print(f"\n{'='*60}")
    print(f"{name}: {metrics['accuracy']*100:.1f}% Accuracy")
    print(f"  TP={metrics['tp']} TN={metrics['tn']} FP={metrics['fp']} FN={metrics['fn']}")
    print(f"  Precision={metrics['precision']:.3f} Recall={metrics['recall']:.3f} F1={metrics['f1']:.3f}")
    print(f"  FPR={metrics['false_positive_rate']:.3f} FNR={metrics['false_negative_rate']:.3f}")
    if per_category:
        print(f"  Pro Kategorie:")
        for cat, m in per_category.items():
            print(f"    {cat}: Acc={m['accuracy']*100:.0f}% "
                  f"(TP={m['tp']} TN={m['tn']} FP={m['fp']} FN={m['fn']} F1={m['f1']:.3f})")


def save_output(output: dict, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nJSON gespeichert: {path}")


def main():
    parser = argparse.ArgumentParser(description="Gatekeeper Evaluator (RQ3)")
    parser.add_argument(
        "--mode", choices=["ast", "alignment", "full"], default="ast",
        help="ast: nur AST, alignment: nur Alignment, full: alle Layer + Sweep",
    )
    parser.add_argument("--output", default=None, help="JSON-Output-Pfad")
    parser.add_argument("--threshold", type=float, default=0.7, help="Alignment-Threshold")
    args = parser.parse_args()

    if args.output is None:
        defaults = {
            "ast": "results/thesis/gatekeeper/ast_only.json",
            "alignment": "results/thesis/gatekeeper/alignment_only.json",
            "full": "results/thesis/gatekeeper/gatekeeper_extended_results.json",
        }
        args.output = defaults[args.mode]

    logging.basicConfig(level=logging.WARNING)

    skills = load_gatekeeper_suite()
    print(f"Gatekeeper Evaluation ({args.mode}): {len(skills)} Skills geladen")

    if args.mode == "ast":
        _run_ast_mode(skills, args)
    else:
        asyncio.run(_run_async_mode(skills, args))


def _run_ast_mode(skills: list[dict], args):
    print(f"\n--- L1: AST-Evaluation ---")
    ast_results = run_ast_evaluation(skills)
    metrics = compute_metrics(ast_results)
    per_cat = compute_per_category(ast_results)
    _print_layer_summary("L1: AST-Only", metrics, per_cat)

    output = {
        "evaluation": "gatekeeper_rq3",
        "mode": "ast",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "corpus_size": len(skills),
        "layers": {
            "ast_only": {"metrics": metrics, "per_category": per_cat},
        },
        "per_skill_results": ast_results,
    }
    save_output(output, Path(args.output))


async def _run_async_mode(skills: list[dict], args):
    output: dict = {
        "evaluation": "gatekeeper_rq3_extended",
        "mode": args.mode,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "corpus_size": len(skills),
        "threshold": args.threshold,
        "layers": {},
    }

    ast_results = None
    if args.mode == "full":
        print(f"\n--- L1: AST-Evaluation (ground_truth=expected_alignment) ---")
        ast_results = run_ast_evaluation(skills, ground_truth_field="expected_alignment")
        ast_metrics = compute_metrics(ast_results)
        ast_cat = compute_per_category(ast_results)
        _print_layer_summary("L1: AST-Only", ast_metrics, ast_cat)
        output["layers"]["ast_only"] = {"metrics": ast_metrics, "per_category": ast_cat}

    print(f"\n--- L2+L3: Alignment-Evaluation (threshold={args.threshold}) ---")
    alignment_results = await run_alignment_evaluation(skills, threshold=args.threshold)
    align_metrics = compute_metrics(alignment_results)
    align_cat = compute_per_category(alignment_results)
    _print_layer_summary("L2+L3: Alignment-Only", align_metrics, align_cat)
    output["layers"]["alignment_only"] = {"metrics": align_metrics, "per_category": align_cat}

    if args.mode == "full" and ast_results is not None:
        print(f"\n--- Combined (AST OR Alignment) ---")
        combined_results = combine_results(ast_results, alignment_results)
        comb_metrics = compute_metrics(combined_results)
        comb_cat = compute_per_category(combined_results)
        _print_layer_summary("Combined (AST OR Alignment)", comb_metrics, comb_cat)
        output["layers"]["combined"] = {"metrics": comb_metrics, "per_category": comb_cat}

        print(f"\n--- Threshold-Sweep ---")
        sweep = await run_threshold_sweep(skills)
        output["threshold_sweep"] = sweep

        output["per_skill_results"] = {
            "ast": ast_results,
            "alignment": alignment_results,
            "combined": combined_results,
        }
    else:
        output["per_skill_results"] = alignment_results

    save_output(output, Path(args.output))


if __name__ == "__main__":
    main()
