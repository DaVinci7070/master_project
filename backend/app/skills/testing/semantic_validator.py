"""
Semantic Validator Service - Validate skill output matches expected behavior.

Goes beyond "code runs" to verify "code solves the problem":
1. Type comparison - output matches expected type
2. Structure comparison - dicts/lists have expected structure
3. LLM-based semantic comparison - meaning matches expectation
"""

import json
import logging
import re
import time
from typing import Any, Optional

from app.core.llm_client import LLMClient
from app.models.schemas.skill_build_schemas import SemanticValidationResult

log = logging.getLogger(__name__)


class SemanticValidator:
    """
    Validates that skill output semantically matches expected behavior.

    Beyond just checking "did it run?", this validates:
    - Type correctness
    - Structure correctness (for complex types)
    - Semantic meaning (using LLM)
    """

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        similarity_threshold: float = 0.7,
    ):
        """
        Initialize semantic validator.

        Args:
            llm_client: LLM for semantic comparison
            similarity_threshold: Minimum similarity score to pass (0-1)
        """
        self.llm = llm_client or LLMClient()
        self.similarity_threshold = similarity_threshold

    async def validate(
        self,
        expected_behavior: str,
        actual_output: Any,
        expected_output: Optional[Any] = None,
        expected_type: str = "any",
        expected_keys: Optional[list[str]] = None,
    ) -> SemanticValidationResult:
        """
        Validate actual output against expected behavior.

        Args:
            expected_behavior: Description of what the output should be
            actual_output: The actual output from skill execution
            expected_output: Optional specific expected value
            expected_type: Expected type ("str", "dict", "list", "int", "float", "bool", "any")
            expected_keys: For dicts, keys that must be present

        Returns:
            SemanticValidationResult with pass/fail and details
        """
        start_time = time.time()

        result = SemanticValidationResult(
            passed=False,
            similarity_score=0.0,
            expected_type=expected_type,
            actual_type=type(actual_output).__name__,
        )

        # Step 1: Type check
        type_match = self._check_type(actual_output, expected_type)
        result.type_match = type_match

        if not type_match and expected_type != "any":
            result.validation_time_ms = int((time.time() - start_time) * 1000)
            return result

        # Step 2: Structure check (for dicts/lists)
        if isinstance(actual_output, dict):
            structure_result = self._check_structure(actual_output, expected_keys)
            result.structure_match = structure_result["match"]
            result.missing_keys = structure_result.get("missing", [])
            result.extra_keys = structure_result.get("extra", [])

            if not result.structure_match and expected_keys:
                result.validation_time_ms = int((time.time() - start_time) * 1000)
                return result

        # Step 3: Value comparison
        if expected_output is not None:
            value_result = await self._compare_values(
                expected_output, actual_output, expected_behavior
            )
            result.similarity_score = value_result["score"]
            result.value_comparison = value_result["comparison"]
            result.llm_reasoning = value_result.get("reasoning")
        else:
            # No expected output - use LLM to validate against behavior
            behavior_result = await self._validate_behavior(
                expected_behavior, actual_output
            )
            result.similarity_score = behavior_result["score"]
            result.llm_reasoning = behavior_result.get("reasoning")

        # Determine pass/fail
        result.passed = (
            result.type_match and
            result.structure_match and
            result.similarity_score >= self.similarity_threshold
        )

        result.validation_time_ms = int((time.time() - start_time) * 1000)

        log.info(
            f"Semantic validation: passed={result.passed}, "
            f"score={result.similarity_score:.2f}, "
            f"type_match={result.type_match}"
        )

        return result

    def _check_type(self, value: Any, expected_type: str) -> bool:
        """Check if value matches expected type."""
        if expected_type == "any":
            return True

        type_map = {
            "str": str,
            "string": str,
            "dict": dict,
            "list": list,
            "int": int,
            "integer": int,
            "float": float,
            "number": (int, float),
            "bool": bool,
            "boolean": bool,
            "none": type(None),
            "null": type(None),
        }

        expected = type_map.get(expected_type.lower())
        if expected is None:
            # Unknown type - assume pass
            return True

        return isinstance(value, expected)

    def _check_structure(
        self,
        actual: dict,
        expected_keys: Optional[list[str]],
    ) -> dict:
        """Check if dict has expected structure."""
        if not expected_keys:
            return {"match": True}

        actual_keys = set(actual.keys())
        expected_set = set(expected_keys)

        missing = expected_set - actual_keys
        # Don't penalize for extra keys - skills may add metadata

        return {
            "match": len(missing) == 0,
            "missing": list(missing),
            "extra": list(actual_keys - expected_set),
        }

    async def _compare_values(
        self,
        expected: Any,
        actual: Any,
        context: str,
    ) -> dict:
        """Compare expected and actual values."""
        # Exact match
        if expected == actual:
            return {
                "score": 1.0,
                "comparison": "Exact match",
            }

        # Type mismatch
        if type(expected) != type(actual):
            # Try string conversion
            if str(expected).strip() == str(actual).strip():
                return {
                    "score": 0.9,
                    "comparison": "String representation matches",
                }

            return {
                "score": 0.3,
                "comparison": f"Type mismatch: expected {type(expected).__name__}, got {type(actual).__name__}",
            }

        # Dict comparison
        if isinstance(expected, dict):
            return self._compare_dicts(expected, actual)

        # List comparison
        if isinstance(expected, list):
            return self._compare_lists(expected, actual)

        # String comparison
        if isinstance(expected, str):
            return await self._compare_strings(expected, actual, context)

        # Numeric comparison
        if isinstance(expected, (int, float)):
            return self._compare_numbers(expected, actual)

        # Default - use LLM
        return await self._llm_compare(expected, actual, context)

    def _compare_dicts(self, expected: dict, actual: dict) -> dict:
        """Compare two dictionaries."""
        expected_keys = set(expected.keys())
        actual_keys = set(actual.keys())

        # Key overlap
        common_keys = expected_keys & actual_keys
        missing_keys = expected_keys - actual_keys

        if not common_keys:
            return {
                "score": 0.2,
                "comparison": f"No common keys. Missing: {list(missing_keys)}",
            }

        # Value comparison for common keys
        matching_values = 0
        for key in common_keys:
            if expected[key] == actual[key]:
                matching_values += 1
            elif str(expected[key]).strip() == str(actual[key]).strip():
                matching_values += 0.8

        key_score = len(common_keys) / len(expected_keys) if expected_keys else 1.0
        value_score = matching_values / len(common_keys) if common_keys else 0.0

        overall_score = (key_score + value_score) / 2

        return {
            "score": overall_score,
            "comparison": f"Keys: {len(common_keys)}/{len(expected_keys)}, Values: {matching_values}/{len(common_keys)}",
        }

    def _compare_lists(self, expected: list, actual: list) -> dict:
        """Compare two lists."""
        if not expected:
            return {
                "score": 1.0 if not actual else 0.5,
                "comparison": "Empty expected list",
            }

        # Length comparison
        length_ratio = min(len(actual), len(expected)) / len(expected)

        # Element comparison (order-sensitive for now)
        matching = 0
        for i, exp_item in enumerate(expected):
            if i < len(actual):
                if exp_item == actual[i]:
                    matching += 1
                elif str(exp_item) == str(actual[i]):
                    matching += 0.8

        element_score = matching / len(expected)

        overall_score = (length_ratio + element_score) / 2

        return {
            "score": overall_score,
            "comparison": f"Length: {len(actual)}/{len(expected)}, Matching: {matching}/{len(expected)}",
        }

    async def _compare_strings(
        self,
        expected: str,
        actual: str,
        context: str,
    ) -> dict:
        """Compare two strings using similarity and LLM."""
        # Normalize
        exp_norm = expected.strip().lower()
        act_norm = actual.strip().lower()

        # Exact match after normalization
        if exp_norm == act_norm:
            return {
                "score": 0.95,
                "comparison": "Normalized match",
            }

        # Substring check
        if exp_norm in act_norm or act_norm in exp_norm:
            containment_ratio = min(len(exp_norm), len(act_norm)) / max(len(exp_norm), len(act_norm))
            return {
                "score": max(0.7, containment_ratio),
                "comparison": "Substring match",
            }

        # For longer strings, use LLM
        if len(expected) > 20 or len(actual) > 20:
            return await self._llm_compare(expected, actual, context)

        # Simple character overlap for short strings
        exp_chars = set(exp_norm)
        act_chars = set(act_norm)
        overlap = len(exp_chars & act_chars)
        score = overlap / max(len(exp_chars), len(act_chars))

        return {
            "score": score,
            "comparison": f"Character overlap: {overlap}/{max(len(exp_chars), len(act_chars))}",
        }

    def _compare_numbers(self, expected: float, actual: float) -> dict:
        """Compare two numbers."""
        if expected == actual:
            return {"score": 1.0, "comparison": "Exact match"}

        # Relative difference
        if expected != 0:
            rel_diff = abs(expected - actual) / abs(expected)
            score = max(0, 1 - rel_diff)
        else:
            # expected is 0
            score = 1.0 if actual == 0 else max(0, 1 - abs(actual))

        return {
            "score": score,
            "comparison": f"Numeric difference: {abs(expected - actual):.4f}",
        }

    async def _llm_compare(
        self,
        expected: Any,
        actual: Any,
        context: str,
    ) -> dict:
        """Use LLM for semantic comparison."""
        try:
            prompt = f"""Compare these two values and rate their semantic similarity.

Context: {context}

Expected value:
{json.dumps(expected, indent=2, default=str)[:1000]}

Actual value:
{json.dumps(actual, indent=2, default=str)[:1000]}

Rate the semantic similarity from 0.0 to 1.0:
- 1.0 = Exact semantic match (same meaning)
- 0.8 = Very similar (minor differences)
- 0.6 = Similar (some differences but same general idea)
- 0.4 = Somewhat related
- 0.2 = Barely related
- 0.0 = Completely different

Respond with ONLY a JSON object:
{{"score": <float>, "reasoning": "<brief explanation>"}}"""

            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": "You are a semantic similarity evaluator. Be objective and precise."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=200,
            )

            # Parse response
            content = response.content
            json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return {
                    "score": float(data.get("score", 0.5)),
                    "comparison": "LLM comparison",
                    "reasoning": data.get("reasoning", ""),
                }

            return {
                "score": 0.5,
                "comparison": "LLM comparison failed to parse",
            }

        except Exception as e:
            log.warning(f"LLM comparison failed: {e}")
            return {
                "score": 0.5,
                "comparison": f"LLM comparison error: {str(e)[:100]}",
            }

    async def _validate_behavior(
        self,
        expected_behavior: str,
        actual_output: Any,
    ) -> dict:
        """Validate output against expected behavior description."""
        try:
            prompt = f"""Evaluate if this output matches the expected behavior.

Expected behavior:
{expected_behavior[:500]}

Actual output:
{json.dumps(actual_output, indent=2, default=str)[:1000]}

Rate how well the output matches the expected behavior from 0.0 to 1.0:
- 1.0 = Perfect match to expected behavior
- 0.8 = Mostly matches with minor issues
- 0.6 = Partially matches
- 0.4 = Somewhat related but significant gaps
- 0.2 = Barely matches
- 0.0 = Does not match at all

Respond with ONLY a JSON object:
{{"score": <float>, "reasoning": "<brief explanation>"}}"""

            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": "You are a behavior validation expert. Be objective and precise."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=200,
            )

            # Parse response
            content = response.content
            json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return {
                    "score": float(data.get("score", 0.5)),
                    "reasoning": data.get("reasoning", ""),
                }

            return {
                "score": 0.5,
                "reasoning": "Failed to parse LLM response",
            }

        except Exception as e:
            log.warning(f"Behavior validation failed: {e}")
            return {
                "score": 0.5,
                "reasoning": f"Validation error: {str(e)[:100]}",
            }

    async def validate_skill_output(
        self,
        skill_name: str,
        capability: str,
        output: dict,
        test_case: Optional[dict] = None,
    ) -> SemanticValidationResult:
        """
        Validate skill output with skill-specific logic.

        Args:
            skill_name: Name of the skill being validated
            capability: Capability the skill provides
            output: Output dict from skill execution
            test_case: Optional test case with expected values

        Returns:
            SemanticValidationResult
        """
        # Check standard skill output structure
        if not isinstance(output, dict):
            return SemanticValidationResult(
                passed=False,
                similarity_score=0.0,
                expected_type="dict",
                actual_type=type(output).__name__,
                type_match=False,
            )

        # Check for success key
        if "success" not in output:
            return SemanticValidationResult(
                passed=False,
                similarity_score=0.3,
                expected_type="dict",
                actual_type="dict",
                type_match=True,
                structure_match=False,
                missing_keys=["success"],
            )

        # If skill reported failure, that's a semantic failure
        if not output.get("success"):
            return SemanticValidationResult(
                passed=False,
                similarity_score=0.2,
                expected_type="dict",
                actual_type="dict",
                type_match=True,
                structure_match=True,
                value_comparison=f"Skill reported failure: {output.get('error', 'Unknown')}",
            )

        # If we have a test case, validate against it
        if test_case:
            expected_output = test_case.get("expected_output")
            expected_type = test_case.get("expected_output_type", "any")
            expected_keys = test_case.get("expected_keys", [])

            return await self.validate(
                expected_behavior=f"Skill {skill_name} for capability: {capability}",
                actual_output=output.get("result"),
                expected_output=expected_output,
                expected_type=expected_type,
                expected_keys=expected_keys,
            )

        # No test case - just validate structure
        return SemanticValidationResult(
            passed=True,
            similarity_score=0.8,
            expected_type="dict",
            actual_type="dict",
            type_match=True,
            structure_match=True,
            value_comparison="No expected output to compare - passed structural validation",
        )
