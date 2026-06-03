import ast
import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


class SkillExecutionError(Exception):
    """Exception raised when skill execution fails."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


@dataclass
class ExecutionResult:
    """Result of executing skill code."""

    success: bool
    output: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0


@dataclass
class TestResult:
    """Result of running a single test case."""

    test_case_index: int
    passed: bool
    input_data: Any = None
    expected_output: Any = None
    actual_output: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0


class SkillExecutor:
    """
    Executor for skill code with sandboxed execution.

    Provides:
    - Code safety validation via AST analysis
    - Restricted execution environment
    - Test case execution and validation

    Usage:
        executor = SkillExecutor()
        result = await executor.execute_code(code, {"value": 42})
        is_valid, results = await executor.validate_skill(code, test_cases)
    """

    SAFE_BUILTINS = {
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "bytes": bytes,
        "callable": callable,
        "chr": chr,
        "complex": complex,
        "dict": dict,
        "divmod": divmod,
        "enumerate": enumerate,
        "filter": filter,
        "float": float,
        "format": format,
        "frozenset": frozenset,
        "getattr": getattr,
        "hasattr": hasattr,
        "hash": hash,
        "hex": hex,
        "int": int,
        "isinstance": isinstance,
        "issubclass": issubclass,
        "iter": iter,
        "len": len,
        "list": list,
        "map": map,
        "max": max,
        "min": min,
        "next": next,
        "object": object,
        "oct": oct,
        "ord": ord,
        "pow": pow,
        "print": print,
        "range": range,
        "repr": repr,
        "reversed": reversed,
        "round": round,
        "set": set,
        "slice": slice,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "type": type,
        "zip": zip,
        "Exception": Exception,
        "ValueError": ValueError,
        "TypeError": TypeError,
        "KeyError": KeyError,
        "IndexError": IndexError,
        "AttributeError": AttributeError,
        "RuntimeError": RuntimeError,
        "StopIteration": StopIteration,
        "ZeroDivisionError": ZeroDivisionError,
        "True": True,
        "False": False,
        "None": None,
    }

    ALLOWED_MODULES = {
        "json",
        "datetime",
        "re",
        "math",
        "collections",
        "itertools",
        "functools",
        "operator",
        "string",
        "decimal",
        "fractions",
        "random",
        "statistics",
        "hashlib",
        "base64",
        "uuid",
        "copy",
        "typing",
    }

    FORBIDDEN_NAMES = {
        "exec",
        "eval",
        "compile",
        "__import__",
        "open",
        "input",
        "breakpoint",
        "globals",
        "locals",
        "vars",
        "dir",
        "delattr",
        "setattr",
        "memoryview",
        "exit",
        "quit",
    }

    FORBIDDEN_ATTRIBUTES = {
        "__class__",
        "__bases__",
        "__subclasses__",
        "__mro__",
        "__globals__",
        "__code__",
        "__closure__",
        "__builtins__",
        "__dict__",
        "__module__",
        "__spec__",
        "__loader__",
        "__import__",
    }

    def __init__(self, timeout_seconds: float = 5.0):
        """
        Initialize the skill executor.

        Args:
            timeout_seconds: Maximum execution time for skill code
        """
        self.timeout_seconds = timeout_seconds

    def _validate_code_safety(self, code: str) -> Tuple[bool, Optional[str]]:
        """
        Validate code safety using AST analysis.

        Checks for:
        - Forbidden function calls (exec, eval, __import__)
        - Forbidden attribute access patterns
        - Unauthorized imports

        Args:
            code: Python code to validate

        Returns:
            Tuple of (is_safe, error_message)
        """
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"Syntax error: {e.msg} at line {e.lineno}"

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in self.FORBIDDEN_NAMES:
                        return False, f"Forbidden function: {node.func.id}"

            if isinstance(node, ast.Attribute):
                if node.attr in self.FORBIDDEN_ATTRIBUTES:
                    return False, f"Forbidden attribute access: {node.attr}"

            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name.split(".")[0]
                    if module_name not in self.ALLOWED_MODULES:
                        return False, f"Forbidden import: {alias.name}"

            if isinstance(node, ast.ImportFrom):
                if node.module:
                    module_name = node.module.split(".")[0]
                    if module_name not in self.ALLOWED_MODULES:
                        return False, f"Forbidden import: {node.module}"

            if isinstance(node, ast.Name):
                if node.id in self.FORBIDDEN_NAMES:
                    if isinstance(node.ctx, ast.Load):
                        return False, f"Forbidden name: {node.id}"

        return True, None

    def _create_safe_globals(self) -> Dict[str, Any]:
        """
        Create a restricted execution environment.

        Returns:
            Dictionary of safe globals for code execution
        """
        safe_globals = {"__builtins__": self.SAFE_BUILTINS.copy()}

        import json as json_module
        import datetime as datetime_module
        import re as re_module
        import math as math_module
        import collections as collections_module
        import itertools as itertools_module
        import functools as functools_module
        import operator as operator_module
        import string as string_module
        import decimal as decimal_module
        import fractions as fractions_module
        import random as random_module
        import statistics as statistics_module
        import hashlib as hashlib_module
        import base64 as base64_module
        import uuid as uuid_module
        import copy as copy_module
        import typing as typing_module

        module_map = {
            "json": json_module,
            "datetime": datetime_module,
            "re": re_module,
            "math": math_module,
            "collections": collections_module,
            "itertools": itertools_module,
            "functools": functools_module,
            "operator": operator_module,
            "string": string_module,
            "decimal": decimal_module,
            "fractions": fractions_module,
            "random": random_module,
            "statistics": statistics_module,
            "hashlib": hashlib_module,
            "base64": base64_module,
            "uuid": uuid_module,
            "copy": copy_module,
            "typing": typing_module,
        }

        def restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
            """Import function that only allows whitelisted modules."""
            base_module = name.split(".")[0]
            if base_module not in self.ALLOWED_MODULES:
                raise ImportError(f"Import of '{name}' is not allowed")
            if base_module in module_map:
                return module_map[base_module]
            raise ImportError(f"Import of '{name}' is not allowed")

        safe_globals["__builtins__"]["__import__"] = restricted_import

        return safe_globals

    async def execute_code(
        self,
        code: str,
        input_data: Any,
        function_name: str = "execute",
    ) -> ExecutionResult:
        """
        Execute skill code with the given input data.

        Args:
            code: Python code containing the function to execute
            input_data: Input data to pass to the function
            function_name: Name of the function to call (default: "execute")

        Returns:
            ExecutionResult with success status, output, and timing
        """
        start_time = time.perf_counter()

        is_safe, error = self._validate_code_safety(code)
        if not is_safe:
            return ExecutionResult(
                success=False,
                error=error,
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )

        safe_globals = self._create_safe_globals()

        try:
            exec(code, safe_globals)

            if function_name not in safe_globals:
                return ExecutionResult(
                    success=False,
                    error=f"Function '{function_name}' not found in code",
                    execution_time_ms=(time.perf_counter() - start_time) * 1000,
                )

            func = safe_globals[function_name]
            if not callable(func):
                return ExecutionResult(
                    success=False,
                    error=f"'{function_name}' is not callable",
                    execution_time_ms=(time.perf_counter() - start_time) * 1000,
                )

            try:
                result = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None, lambda: func(input_data)
                    ),
                    timeout=self.timeout_seconds,
                )
                return ExecutionResult(
                    success=True,
                    output=result,
                    execution_time_ms=(time.perf_counter() - start_time) * 1000,
                )
            except asyncio.TimeoutError:
                return ExecutionResult(
                    success=False,
                    error=f"Execution timed out after {self.timeout_seconds} seconds",
                    execution_time_ms=(time.perf_counter() - start_time) * 1000,
                )

        except Exception as e:
            return ExecutionResult(
                success=False,
                error=f"{type(e).__name__}: {str(e)}",
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )

    async def run_test_case(
        self,
        code: str,
        test_case: Dict[str, Any],
        test_index: int,
        function_name: str = "execute",
    ) -> TestResult:
        """
        Run a single test case against skill code.

        Args:
            code: Python code to test
            test_case: Dict with 'input' and 'expected_output' keys
            test_index: Index of this test case (for tracking)
            function_name: Name of the function to call

        Returns:
            TestResult with pass/fail status and details
        """
        input_data = test_case.get("input")
        expected_output = test_case.get("expected_output")

        result = await self.execute_code(code, input_data, function_name)

        if not result.success:
            return TestResult(
                test_case_index=test_index,
                passed=False,
                input_data=input_data,
                expected_output=expected_output,
                actual_output=None,
                error=result.error,
                execution_time_ms=result.execution_time_ms,
            )

        passed = self._compare_outputs(result.output, expected_output)

        return TestResult(
            test_case_index=test_index,
            passed=passed,
            input_data=input_data,
            expected_output=expected_output,
            actual_output=result.output,
            error=None if passed else "Output mismatch",
            execution_time_ms=result.execution_time_ms,
        )

    def _compare_outputs(self, actual: Any, expected: Any) -> bool:
        """
        Compare actual output to expected output.

        Handles JSON serialization for complex types and
        allows for minor floating point differences.

        Args:
            actual: The actual output from execution
            expected: The expected output from test case

        Returns:
            True if outputs match, False otherwise
        """
        if actual == expected:
            return True

        if isinstance(actual, float) and isinstance(expected, (int, float)):
            return abs(actual - expected) < 1e-9
        if isinstance(expected, float) and isinstance(actual, (int, float)):
            return abs(actual - expected) < 1e-9

        try:
            actual_json = json.dumps(actual, sort_keys=True, default=str)
            expected_json = json.dumps(expected, sort_keys=True, default=str)
            return actual_json == expected_json
        except (TypeError, ValueError):
            pass

        return False

    async def validate_skill(
        self,
        code: str,
        test_cases: List[Dict[str, Any]],
        function_name: str = "execute",
    ) -> Tuple[bool, List[TestResult]]:
        """
        Validate a skill by running all its test cases.

        This is the DB-06 gate: skills cannot be activated unless
        all test cases pass.

        Args:
            code: Python code to validate
            test_cases: List of test case dicts with 'input' and 'expected_output'
            function_name: Name of the function to call

        Returns:
            Tuple of (all_passed, list_of_test_results)
        """
        if not test_cases:
            return True, []

        results = []
        for idx, test_case in enumerate(test_cases):
            result = await self.run_test_case(code, test_case, idx, function_name)
            results.append(result)

        all_passed = all(r.passed for r in results)
        return all_passed, results
