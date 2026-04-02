"""
Pydantic schemas for Tool Builder operations.

These schemas handle validation for:
- Tool specification requests (ToolSpecification)
- Generated tool outputs (GeneratedTool, TestCase)
- Tool modification requests (ToolModificationRequest, ToolModification)
- Code validation results (ValidationResult)
- Sandbox execution results (SandboxResult)
"""
import builtins
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# Python builtins that cannot be used as skill names
PYTHON_BUILTINS = set(dir(builtins))


class ToolSpecification(BaseModel):
    """
    Schema for requesting a new tool generation.

    Used by ToolBuilderService to generate Python functions (skills)
    from natural language specifications with schema contracts.
    """
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern=r'^[a-z][a-z0-9_]*$',
        description="Snake_case function name"
    )
    description: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="What the skill does"
    )
    input_schema: dict[str, Any] = Field(
        ...,
        description="JSON schema for function parameters"
    )
    output_schema: dict[str, Any] = Field(
        ...,
        description="JSON schema for return value"
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Hard requirements to enforce"
    )
    examples: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Example input/output pairs"
    )
    parent_skill_id: Optional[str] = Field(
        None,
        min_length=36,
        max_length=36,
        description="UUID of parent skill for modifications"
    )

    @field_validator('name')
    @classmethod
    def name_not_builtin(cls, v: str) -> str:
        """Ensure skill name is not a Python builtin."""
        if v in PYTHON_BUILTINS:
            raise ValueError(f"'{v}' is a Python builtin and cannot be used as a skill name")
        return v


class TestCase(BaseModel):
    """
    Schema representing a single pytest test case.

    Each test validates a specific aspect of skill behavior:
    basic functionality, edge cases, or error handling.
    """
    name: str = Field(
        ...,
        pattern=r'^test_[a-z][a-z0-9_]*$',
        description="Test function name (must start with test_)"
    )
    description: str = Field(
        ...,
        description="What this test validates"
    )
    test_code: str = Field(
        ...,
        description="Complete pytest test function code"
    )
    test_type: Literal["basic", "edge_case", "error_handling"] = Field(
        ...,
        description="Categorization of test type"
    )


class GeneratedTool(BaseModel):
    """
    LLM output schema for tool generation.

    Structured output from meta-prompting LLM call when generating
    a new Python function (skill).
    """
    code: str = Field(
        ...,
        min_length=50,
        description="Complete Python function code with docstring and type hints"
    )
    test_cases: list[TestCase] = Field(
        ...,
        min_length=3,
        description="Pytest test cases (minimum 3 required)"
    )
    imports: list[str] = Field(
        ...,
        description="Required imports from allowlist"
    )
    rationale: str = Field(
        ...,
        min_length=20,
        description="Explanation of design decisions"
    )
    complexity: str = Field(
        ...,
        description="Algorithmic complexity (e.g., 'O(n) time, O(1) space')"
    )
    edge_cases_handled: list[str] = Field(
        ...,
        description="Which edge cases are covered"
    )


class ToolModificationRequest(BaseModel):
    """
    Schema for requesting modification of an existing skill.

    Captures finding context and improvement direction to guide
    targeted code modification.
    """
    skill_id: str = Field(
        ...,
        min_length=36,
        max_length=36,
        description="UUID of skill to modify"
    )
    finding_description: str = Field(
        ...,
        min_length=20,
        description="What issue was identified"
    )
    improvement_direction: str = Field(
        ...,
        min_length=20,
        description="How to address the issue"
    )


class ToolModification(BaseModel):
    """
    LLM output schema for tool modification.

    Structured output from meta-prompting LLM call when modifying
    an existing skill to address a finding.
    """
    modified_code: str = Field(
        ...,
        min_length=50,
        description="Updated Python function code"
    )
    modified_tests: list[TestCase] = Field(
        ...,
        description="Updated test cases"
    )
    changes_made: list[str] = Field(
        ...,
        description="List of specific changes"
    )
    rationale: str = Field(
        ...,
        min_length=20,
        description="Why changes address the finding"
    )


class ValidationResult(BaseModel):
    """
    Output schema from CodeValidatorService.

    Captures results of static analysis on generated code,
    including safety checks and import validation.
    """
    is_valid: bool = Field(
        ...,
        description="Whether code passed all validation checks"
    )
    errors: list[str] = Field(
        default_factory=list,
        description="Validation errors found"
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-blocking issues"
    )
    blocked_constructs: list[str] = Field(
        default_factory=list,
        description="Dangerous patterns detected"
    )
    imports_used: list[str] = Field(
        default_factory=list,
        description="Imports found in code"
    )


class SandboxResult(BaseModel):
    """
    Output schema from SandboxExecutorService.

    Captures results of executing generated code in an isolated
    sandbox environment with resource limits.
    """
    success: bool = Field(
        ...,
        description="Whether all tests passed"
    )
    exit_code: int = Field(
        ...,
        description="Process exit code"
    )
    stdout: str = Field(
        default="",
        description="Standard output"
    )
    stderr: str = Field(
        default="",
        description="Standard error"
    )
    duration_seconds: float = Field(
        ...,
        description="Execution duration in seconds"
    )
    timeout: bool = Field(
        default=False,
        description="Whether execution exceeded time limit"
    )
    oom_killed: bool = Field(
        default=False,
        description="Whether process was killed for exceeding memory limit"
    )
    tests_passed: int = Field(
        default=0,
        description="Number of tests passed"
    )
    tests_failed: int = Field(
        default=0,
        description="Number of tests failed"
    )
    test_output: str = Field(
        default="",
        description="Pytest output"
    )
