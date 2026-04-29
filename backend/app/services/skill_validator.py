"""Skill validation service with parent regression check."""
import json
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sql.versioned_models import Skill
from app.models.schemas.skill_build_schemas import (
    ActivationResult,
    ComparisonResult,
    TestSuiteResult,
)
from app.services.dynamic_sandbox_service import DynamicSandboxService

logger = logging.getLogger(__name__)


class SkillValidator:
    """
    Validates skills before activation.

    Runs the skill's test_cases in sandbox and, if the skill has a parent,
    compares scores to prevent regressions (new_score must be >= parent_score).
    """

    def __init__(self, session_factory, sandbox: DynamicSandboxService):
        self.session_factory = session_factory
        self.sandbox = sandbox

    async def validate_for_activation(
        self,
        skill: Skill,
    ) -> ActivationResult:
        """
        Full validation gate: sandbox tests + parent comparison.

        Args:
            skill: The skill to validate (must have .code and .test_cases)

        Returns:
            ActivationResult with approved/rejected status
        """
        # 1. Run test suite on new skill
        new_result = await self._run_test_suite(skill)

        if new_result.total == 0:
            logger.info(f"Skill {skill.name}: no test cases, auto-approved")
            return ActivationResult(
                approved=True,
                reason="No test cases defined",
                test_result=new_result,
            )

        if new_result.score == 0.0:
            return ActivationResult(
                approved=False,
                reason=f"All {new_result.total} tests failed",
                test_result=new_result,
            )

        # 2. Parent comparison if applicable
        if skill.parent_id:
            async with self.session_factory() as db:
                parent = await db.execute(
                    select(Skill).where(Skill.id == skill.parent_id)
                )
                parent_skill = parent.scalar_one_or_none()

            if parent_skill and parent_skill.code:
                comparison = await self._compare_with_parent(skill, parent_skill, new_result)

                if comparison.regression:
                    logger.warning(
                        f"Skill {skill.name}: regression vs parent "
                        f"(new={comparison.new_score:.2f}, parent={comparison.parent_score:.2f})"
                    )
                    return ActivationResult(
                        approved=False,
                        reason=(
                            f"Regression vs parent: new score {comparison.new_score:.2f} "
                            f"< parent score {comparison.parent_score:.2f}"
                        ),
                        test_result=new_result,
                        comparison=comparison,
                    )

                logger.info(
                    f"Skill {skill.name}: parent comparison passed "
                    f"(new={comparison.new_score:.2f}, parent={comparison.parent_score:.2f})"
                )
                return ActivationResult(
                    approved=True,
                    reason="Passed parent comparison",
                    test_result=new_result,
                    comparison=comparison,
                )

        logger.info(f"Skill {skill.name}: validated ({new_result.passed}/{new_result.total} passed)")
        return ActivationResult(
            approved=True,
            reason=f"{new_result.passed}/{new_result.total} tests passed",
            test_result=new_result,
        )

    async def _run_test_suite(self, skill: Skill) -> TestSuiteResult:
        """Run all test_cases from skill in sandbox."""
        test_cases = skill.test_cases or []
        if not test_cases or not skill.code:
            return TestSuiteResult()

        deps = skill.dependencies or {}
        pip_reqs = deps.get("pip", [])
        sys_pkgs = deps.get("system", [])

        passed = 0
        failed = 0
        details = []

        for tc in test_cases:
            tc_name = tc.get("name", "unnamed")
            tc_input = tc.get("input_data", tc.get("input", {}))
            expected_keys = tc.get("expected_keys", [])

            test_code = self._build_single_test(skill.code, tc_input, expected_keys)

            result = await self.sandbox.execute(
                code=test_code,
                pip_requirements=pip_reqs,
                system_packages=sys_pkgs,
            )

            tc_passed = result.success and "TEST PASSED" in (result.stdout or "")
            if tc_passed:
                passed += 1
            else:
                failed += 1

            details.append({
                "name": tc_name,
                "passed": tc_passed,
                "error": result.error or result.stderr if not tc_passed else None,
            })

        total = passed + failed
        score = passed / total if total > 0 else 0.0

        return TestSuiteResult(
            passed=passed,
            failed=failed,
            total=total,
            score=score,
            details=details,
        )

    async def _compare_with_parent(
        self,
        skill: Skill,
        parent: Skill,
        new_result: Optional[TestSuiteResult] = None,
    ) -> ComparisonResult:
        """Compare skill against its parent using union of test cases."""
        # Union of test cases from both skills
        new_tests = skill.test_cases or []
        parent_tests = parent.test_cases or []

        # Merge: use all tests, deduplicate by name
        seen_names = set()
        combined_tests = []
        for tc in new_tests + parent_tests:
            name = tc.get("name", "")
            if name not in seen_names:
                combined_tests.append(tc)
                seen_names.add(name)

        if not combined_tests:
            return ComparisonResult(details="No test cases available for comparison")

        # Create temporary skill-like objects with combined test cases for scoring
        # Run new skill with combined tests
        new_score = await self._score_with_tests(skill, combined_tests)

        # Run parent with combined tests
        parent_score = await self._score_with_tests(parent, combined_tests)

        regression = new_score < parent_score

        return ComparisonResult(
            new_score=new_score,
            parent_score=parent_score,
            regression=regression,
            details=(
                f"Tested {len(combined_tests)} cases: "
                f"new={new_score:.2f}, parent={parent_score:.2f}"
            ),
        )

    async def _score_with_tests(self, skill: Skill, test_cases: list[dict]) -> float:
        """Run a set of test cases against a skill and return pass rate."""
        if not skill.code or not test_cases:
            return 0.0

        deps = skill.dependencies or {}
        pip_reqs = deps.get("pip", [])
        sys_pkgs = deps.get("system", [])

        passed = 0
        total = len(test_cases)

        for tc in test_cases:
            tc_input = tc.get("input_data", tc.get("input", {}))
            expected_keys = tc.get("expected_keys", [])

            test_code = self._build_single_test(skill.code, tc_input, expected_keys)

            result = await self.sandbox.execute(
                code=test_code,
                pip_requirements=pip_reqs,
                system_packages=sys_pkgs,
            )

            if result.success and "TEST PASSED" in (result.stdout or ""):
                passed += 1

        return passed / total if total > 0 else 0.0

    @staticmethod
    def _build_single_test(code: str, test_input: dict, expected_keys: list[str] = None) -> str:
        """Build test wrapper for a single test case."""
        expected_keys = expected_keys or []

        # If no input or file references, do smoke test
        file_keys = {"file_path", "audio_file_path", "path", "input_file", "filepath"}
        has_file_ref = any(
            k.lower() in file_keys and isinstance(v, str)
            for k, v in test_input.items()
        )

        if not test_input or has_file_ref:
            return f'''{code}

# Smoke test
if __name__ == "__main__":
    import inspect
    if not callable(execute):
        print("ERROR: execute is not callable")
        exit(1)
    print("TEST PASSED")
    exit(0)
'''

        keys_check = ""
        if expected_keys:
            keys_str = json.dumps(expected_keys)
            keys_check = f'''
    for key in {keys_str}:
        if key not in result:
            print(f"ERROR: Missing expected key '{{key}}'")
            exit(1)'''

        return f'''{code}

# Test wrapper
if __name__ == "__main__":
    import json
    test_input = {json.dumps(test_input)}

    try:
        result = execute(test_input)
        if not isinstance(result, dict):
            print("ERROR: Result must be a dict")
            exit(1)
        if "success" not in result:
            print("ERROR: Result must have 'success' key")
            exit(1){keys_check}
        if result.get("success"):
            print("TEST PASSED")
            exit(0)
        else:
            print("TEST FAILED:", result.get("error", "Unknown"))
            exit(1)
    except Exception as e:
        print(f"EXCEPTION: {{type(e).__name__}}: {{e}}")
        exit(1)
'''