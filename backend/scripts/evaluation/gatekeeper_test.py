from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.skills.testing.code_validator import CodeValidatorService

DATASETS_DIR = Path(__file__).parent / "datasets"


def run_gatekeeper_test(args: argparse.Namespace) -> dict:
    path = DATASETS_DIR / "gatekeeper_skills.yaml"
    if not path.exists():
        print(f"Error: {path} not found")
        sys.exit(1)

    with open(path) as f:
        suite = yaml.safe_load(f)

    validator = CodeValidatorService()
    skills = suite["skills"]

    results = []
    tp = fp = tn = fn = 0

    for skill in skills:
        skill_id = skill["skill_id"]
        category = skill["category"]
        expected = skill["expected_validation"]
        code = skill["code"]

        validation = validator.validate(code)
        actual = "pass" if validation.is_valid else "block"
        correct = actual == expected

        if category == "unsafe" and actual == "block":
            tp += 1
        elif category == "safe" and actual == "block":
            fp += 1
        elif category == "safe" and actual == "pass":
            tn += 1
        elif category == "unsafe" and actual == "pass":
            fn += 1

        mark = "OK" if correct else "MISMATCH"
        print(f"  {skill_id:35s} [{category:6s}] expected={expected:5s} actual={actual:5s} {mark}")
        if not correct:
            print(f"    blocked_constructs: {validation.blocked_constructs}")
            print(f"    errors: {validation.errors}")

        results.append({
            "skill_id": skill_id,
            "category": category,
            "expected": expected,
            "actual": actual,
            "correct": correct,
            "is_valid": validation.is_valid,
            "blocked_constructs": validation.blocked_constructs,
            "errors": validation.errors,
        })

    total = len(skills)
    safe_count = sum(1 for s in skills if s["category"] == "safe")
    unsafe_count = sum(1 for s in skills if s["category"] == "unsafe")
    correct_count = sum(1 for r in results if r["correct"])

    fnr = fn / unsafe_count if unsafe_count else 0.0
    fpr = fp / safe_count if safe_count else 0.0

    output = {
        "suite": "gatekeeper_skills",
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "total_skills": total,
        "safe_skills": safe_count,
        "unsafe_skills": unsafe_count,
        "correct": correct_count,
        "accuracy": round(correct_count / total, 3) if total else 0.0,
        "true_positives": tp,
        "false_positives": fp,
        "true_negatives": tn,
        "false_negatives": fn,
        "false_negative_rate": round(fnr, 3),
        "false_positive_rate": round(fpr, 3),
        "results": results,
    }

    print(f"\n{'='*60}")
    print(f"Gatekeeper Test Results")
    print(f"{'='*60}")
    print(f"Total: {total} skills ({safe_count} safe, {unsafe_count} unsafe)")
    print(f"Correct: {correct_count}/{total} ({output['accuracy']*100:.1f}%)")
    print(f"TP={tp}  FP={fp}  TN={tn}  FN={fn}")
    print(f"False Negative Rate: {fnr*100:.1f}% (unsafe skills that passed)")
    print(f"False Positive Rate: {fpr*100:.1f}% (safe skills that were blocked)")

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"\nJSON written to {output_path}")

    return output


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Gatekeeper Security Benchmark")
    parser.add_argument("--output", default=None, help="Path for JSON output")
    args = parser.parse_args(argv)

    print("Gatekeeper Security Benchmark\n")
    run_gatekeeper_test(args)


if __name__ == "__main__":
    main()
