"""
Tests for SkillExecutor and skill validation.

Covers:
- Basic code execution
- Safe module imports
- Forbidden code patterns (exec, eval, dangerous imports)
- Test case validation
- Timeout handling
- Error scenarios
"""
import pytest
from app.services.skill_executor import (
    SkillExecutor,
    ExecutionResult,
    TestResult,
    SkillExecutionError,
)


class TestSkillExecution:
    """Tests for SkillExecutor.execute_code()"""

    @pytest.mark.asyncio
    async def test_simple_function_execution(self, skill_executor):
        """Test executing a simple function."""
        code = '''
def execute(data):
    return data.get("value", 0) * 2
'''
        result = await skill_executor.execute_code(
            code, {"value": 5}
        )

        assert result.success is True
        assert result.output == 10
        assert result.error is None
        assert result.execution_time_ms > 0

    @pytest.mark.asyncio
    async def test_json_return(self, skill_executor):
        """Test function returning JSON-serializable dict."""
        code = '''
def execute(data):
    return {
        "original": data.get("value"),
        "doubled": data.get("value", 0) * 2,
        "items": [1, 2, 3]
    }
'''
        result = await skill_executor.execute_code(
            code, {"value": 7}
        )

        assert result.success is True
        assert result.output == {
            "original": 7,
            "doubled": 14,
            "items": [1, 2, 3]
        }

    @pytest.mark.asyncio
    async def test_allowed_module_json(self, skill_executor):
        """Test using allowed json module."""
        code = '''
import json

def execute(data):
    serialized = json.dumps(data)
    return json.loads(serialized)
'''
        result = await skill_executor.execute_code(
            code, {"key": "value"}
        )

        assert result.success is True
        assert result.output == {"key": "value"}

    @pytest.mark.asyncio
    async def test_allowed_module_math(self, skill_executor):
        """Test using allowed math module."""
        code = '''
import math

def execute(data):
    value = data.get("value", 0)
    return {
        "sqrt": math.sqrt(abs(value)),
        "ceil": math.ceil(value),
        "floor": math.floor(value)
    }
'''
        result = await skill_executor.execute_code(
            code, {"value": 4.5}
        )

        assert result.success is True
        assert result.output["sqrt"] == pytest.approx(2.1213, rel=1e-3)
        assert result.output["ceil"] == 5
        assert result.output["floor"] == 4

    @pytest.mark.asyncio
    async def test_allowed_module_datetime(self, skill_executor):
        """Test using allowed datetime module."""
        code = '''
from datetime import datetime, timedelta

def execute(data):
    days = data.get("days", 0)
    now = datetime.now()
    future = now + timedelta(days=days)
    return {
        "now": now.isoformat(),
        "future": future.isoformat()
    }
'''
        result = await skill_executor.execute_code(
            code, {"days": 7}
        )

        assert result.success is True
        assert "now" in result.output
        assert "future" in result.output

    @pytest.mark.asyncio
    async def test_allowed_module_re(self, skill_executor):
        """Test using allowed re module."""
        code = '''
import re

def execute(data):
    text = data.get("text", "")
    pattern = data.get("pattern", r"\\w+")
    matches = re.findall(pattern, text)
    return {"matches": matches}
'''
        result = await skill_executor.execute_code(
            code, {"text": "hello world 123", "pattern": r"\d+"}
        )

        assert result.success is True
        assert result.output == {"matches": ["123"]}

    @pytest.mark.asyncio
    async def test_allowed_module_collections(self, skill_executor):
        """Test using allowed collections module."""
        code = '''
from collections import Counter, defaultdict

def execute(data):
    items = data.get("items", [])
    counter = Counter(items)
    return dict(counter.most_common())
'''
        result = await skill_executor.execute_code(
            code, {"items": ["a", "b", "a", "c", "a", "b"]}
        )

        assert result.success is True
        assert result.output == {"a": 3, "b": 2, "c": 1}

    @pytest.mark.asyncio
    async def test_forbidden_import_os(self, skill_executor):
        """Test that os import is blocked."""
        code = '''
import os

def execute(data):
    return os.getcwd()
'''
        result = await skill_executor.execute_code(code, {})

        assert result.success is False
        assert "Forbidden import" in result.error

    @pytest.mark.asyncio
    async def test_forbidden_import_subprocess(self, skill_executor):
        """Test that subprocess import is blocked."""
        code = '''
import subprocess

def execute(data):
    return subprocess.run(["ls"], capture_output=True)
'''
        result = await skill_executor.execute_code(code, {})

        assert result.success is False
        assert "Forbidden import" in result.error

    @pytest.mark.asyncio
    async def test_forbidden_import_sys(self, skill_executor):
        """Test that sys import is blocked."""
        code = '''
import sys

def execute(data):
    return sys.path
'''
        result = await skill_executor.execute_code(code, {})

        assert result.success is False
        assert "Forbidden import" in result.error

    @pytest.mark.asyncio
    async def test_forbidden_function_exec(self, skill_executor):
        """Test that exec() is blocked."""
        code = '''
def execute(data):
    exec("x = 1 + 1")
    return x
'''
        result = await skill_executor.execute_code(code, {})

        assert result.success is False
        assert "Forbidden" in result.error

    @pytest.mark.asyncio
    async def test_forbidden_function_eval(self, skill_executor):
        """Test that eval() is blocked."""
        code = '''
def execute(data):
    return eval("1 + 1")
'''
        result = await skill_executor.execute_code(code, {})

        assert result.success is False
        assert "Forbidden" in result.error

    @pytest.mark.asyncio
    async def test_forbidden_function_compile(self, skill_executor):
        """Test that compile() is blocked."""
        code = '''
def execute(data):
    code = compile("x = 1", "<string>", "exec")
    return code
'''
        result = await skill_executor.execute_code(code, {})

        assert result.success is False
        assert "Forbidden" in result.error

    @pytest.mark.asyncio
    async def test_forbidden_function_open(self, skill_executor):
        """Test that open() is blocked."""
        code = '''
def execute(data):
    with open("/etc/passwd", "r") as f:
        return f.read()
'''
        result = await skill_executor.execute_code(code, {})

        assert result.success is False
        assert "Forbidden" in result.error

    @pytest.mark.asyncio
    async def test_forbidden_attribute_globals(self, skill_executor):
        """Test that __globals__ access is blocked."""
        code = '''
def execute(data):
    return execute.__globals__
'''
        result = await skill_executor.execute_code(code, {})

        assert result.success is False
        assert "Forbidden attribute" in result.error

    @pytest.mark.asyncio
    async def test_forbidden_attribute_builtins(self, skill_executor):
        """Test that __builtins__ access is blocked."""
        code = '''
def execute(data):
    return __builtins__
'''
        result = await skill_executor.execute_code(code, {})

        assert result.success is False
        assert "Forbidden" in result.error

    @pytest.mark.asyncio
    async def test_syntax_error(self, skill_executor):
        """Test handling of syntax errors."""
        code = '''
def execute(data)
    return data
'''
        result = await skill_executor.execute_code(code, {})

        assert result.success is False
        assert "Syntax error" in result.error

    @pytest.mark.asyncio
    async def test_missing_function(self, skill_executor):
        """Test handling of missing execute function."""
        code = '''
def process(data):
    return data
'''
        result = await skill_executor.execute_code(code, {})

        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_runtime_error(self, skill_executor):
        """Test handling of runtime errors."""
        code = '''
def execute(data):
    return 1 / 0
'''
        result = await skill_executor.execute_code(code, {})

        assert result.success is False
        assert "ZeroDivisionError" in result.error

    @pytest.mark.asyncio
    async def test_timeout(self, skill_executor):
        """Test that infinite loops are terminated."""
        code = '''
def execute(data):
    while True:
        pass
    return "never"
'''
        result = await skill_executor.execute_code(code, {})

        assert result.success is False
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_custom_function_name(self, skill_executor):
        """Test calling a custom function name."""
        code = '''
def process_data(data):
    return data.get("value", 0) + 100
'''
        result = await skill_executor.execute_code(
            code, {"value": 42}, function_name="process_data"
        )

        assert result.success is True
        assert result.output == 142


class TestSkillValidation:
    """Tests for SkillExecutor.validate_skill()"""

    @pytest.mark.asyncio
    async def test_all_tests_pass(
        self, skill_executor, sample_skill_code, sample_test_cases
    ):
        """Test validation with all tests passing."""
        passed, results = await skill_executor.validate_skill(
            sample_skill_code, sample_test_cases
        )

        assert passed is True
        assert len(results) == 3
        assert all(r.passed for r in results)

    @pytest.mark.asyncio
    async def test_failing_test_detected(self, skill_executor):
        """Test that failing tests are detected."""
        code = '''
def execute(data):
    return data.get("value", 0) * 2
'''
        test_cases = [
            {"input": {"value": 5}, "expected_output": 10},  # Pass
            {"input": {"value": 3}, "expected_output": 100},  # Fail - wrong expectation
            {"input": {"value": 7}, "expected_output": 14},  # Pass
        ]

        passed, results = await skill_executor.validate_skill(
            code, test_cases
        )

        assert passed is False
        assert len(results) == 3
        assert results[0].passed is True
        assert results[1].passed is False
        assert results[1].actual_output == 6
        assert results[1].expected_output == 100
        assert results[2].passed is True

    @pytest.mark.asyncio
    async def test_empty_test_cases(self, skill_executor, sample_skill_code):
        """Test validation with empty test cases."""
        passed, results = await skill_executor.validate_skill(
            sample_skill_code, []
        )

        assert passed is True
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_execution_error_in_test(self, skill_executor):
        """Test handling of execution errors during validation."""
        code = '''
def execute(data):
    # This will fail for value=0
    return 100 / data.get("value", 0)
'''
        test_cases = [
            {"input": {"value": 10}, "expected_output": 10},  # Pass
            {"input": {"value": 0}, "expected_output": 0},  # Error - division by zero
        ]

        passed, results = await skill_executor.validate_skill(
            code, test_cases
        )

        assert passed is False
        assert len(results) == 2
        assert results[0].passed is True
        assert results[1].passed is False
        assert "ZeroDivisionError" in results[1].error

    @pytest.mark.asyncio
    async def test_validation_with_json_output(self, skill_executor):
        """Test validation with JSON-serializable output."""
        code = '''
import json

def execute(data):
    return {
        "name": data.get("name", "unknown"),
        "count": data.get("count", 0) * 2,
        "items": ["a", "b", "c"]
    }
'''
        test_cases = [
            {
                "input": {"name": "test", "count": 5},
                "expected_output": {
                    "name": "test",
                    "count": 10,
                    "items": ["a", "b", "c"]
                }
            }
        ]

        passed, results = await skill_executor.validate_skill(
            code, test_cases
        )

        assert passed is True
        assert results[0].passed is True

    @pytest.mark.asyncio
    async def test_validation_with_float_comparison(self, skill_executor):
        """Test that float comparison handles precision."""
        code = '''
def execute(data):
    return data.get("value", 0) / 3.0
'''
        test_cases = [
            # 1/3 has infinite decimal places
            {"input": {"value": 1}, "expected_output": 0.3333333333333333}
        ]

        passed, results = await skill_executor.validate_skill(
            code, test_cases
        )

        assert passed is True

    @pytest.mark.asyncio
    async def test_validation_records_timing(self, skill_executor, sample_skill_code):
        """Test that validation records execution time."""
        test_cases = [
            {"input": {"value": 5}, "expected_output": 10}
        ]

        passed, results = await skill_executor.validate_skill(
            sample_skill_code, test_cases
        )

        assert results[0].execution_time_ms > 0


class TestCodeSafetyValidation:
    """Tests for SkillExecutor._validate_code_safety()"""

    def test_safe_code_passes(self, skill_executor, sample_skill_code):
        """Test that safe code passes validation."""
        is_safe, error = skill_executor._validate_code_safety(sample_skill_code)

        assert is_safe is True
        assert error is None

    def test_code_with_allowed_imports_passes(self, skill_executor, code_with_allowed_import):
        """Test that code with allowed imports passes."""
        is_safe, error = skill_executor._validate_code_safety(code_with_allowed_import)

        assert is_safe is True
        assert error is None

    def test_exec_blocked(self, skill_executor, dangerous_code_exec):
        """Test that exec is blocked."""
        is_safe, error = skill_executor._validate_code_safety(dangerous_code_exec)

        assert is_safe is False
        assert "Forbidden" in error

    def test_dangerous_import_blocked(self, skill_executor, dangerous_code_import):
        """Test that dangerous imports are blocked."""
        is_safe, error = skill_executor._validate_code_safety(dangerous_code_import)

        assert is_safe is False
        assert "Forbidden import" in error

    def test_syntax_error_detected(self, skill_executor):
        """Test that syntax errors are detected."""
        code = "def foo( return"
        is_safe, error = skill_executor._validate_code_safety(code)

        assert is_safe is False
        assert "Syntax error" in error


class TestDataclasses:
    """Tests for ExecutionResult and TestResult dataclasses."""

    def test_execution_result_success(self):
        """Test ExecutionResult for successful execution."""
        result = ExecutionResult(
            success=True,
            output={"key": "value"},
            execution_time_ms=123.45
        )

        assert result.success is True
        assert result.output == {"key": "value"}
        assert result.error is None
        assert result.execution_time_ms == 123.45

    def test_execution_result_failure(self):
        """Test ExecutionResult for failed execution."""
        result = ExecutionResult(
            success=False,
            error="Something went wrong",
            execution_time_ms=50.0
        )

        assert result.success is False
        assert result.output is None
        assert result.error == "Something went wrong"

    def test_test_result_passed(self):
        """Test TestResult for passing test."""
        result = TestResult(
            test_case_index=0,
            passed=True,
            input_data={"value": 5},
            expected_output=10,
            actual_output=10,
            execution_time_ms=25.0
        )

        assert result.passed is True
        assert result.error is None
        assert result.actual_output == result.expected_output

    def test_test_result_failed(self):
        """Test TestResult for failing test."""
        result = TestResult(
            test_case_index=1,
            passed=False,
            input_data={"value": 5},
            expected_output=10,
            actual_output=15,
            error="Output mismatch",
            execution_time_ms=30.0
        )

        assert result.passed is False
        assert result.error == "Output mismatch"
        assert result.actual_output != result.expected_output

    def test_skill_execution_error(self):
        """Test SkillExecutionError exception."""
        error = SkillExecutionError(
            "Execution failed",
            details={"skill_id": "abc123"}
        )

        assert str(error) == "Execution failed"
        assert error.message == "Execution failed"
        assert error.details == {"skill_id": "abc123"}
