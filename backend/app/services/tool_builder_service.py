"""
Tool Builder Service for generating and modifying Python skills.

This service implements the Tool Builder agent that can:
- Generate new Python skills from specifications via meta-prompting
- Modify existing skills to address identified issues
- Validate generated code via CodeValidatorService before persistence
- Generate test cases alongside code (test-first pattern)
- Track rationale and version history via parent-child relationships

Flow:
    ControlAgent decides improvement -> ToolBuilderService.generate_tool/modify_tool()
    -> Code validated via CodeValidatorService -> New skill version created
    -> Sandbox execution validates (06-05) -> A/B testing validates -> Promote or rollback
"""
import json
import logging
from typing import Optional

from pydantic import ValidationError

from app.core.llm_client import LLMClient, LLMError
from app.models.schemas.tool_builder_schemas import (
    ToolSpecification,
    ToolModificationRequest,
    GeneratedTool,
    ToolModification,
    TestCase,
)
from app.models.sql.versioned_models import Skill
from app.repositories.skill_repository import SkillRepository
from app.services.code_validator_service import CodeValidatorService
from app.prompts.tool_builder_prompt import (
    TOOL_BUILDER_SYSTEM_PROMPT,
    TOOL_MODIFICATION_SYSTEM_PROMPT,
)

log = logging.getLogger(__name__)


class ToolBuilderService:
    """
    Tool Builder: generates and modifies Python skills via meta-prompting.

    Uses LLM meta-prompting with structured output to create/modify skills
    while enforcing safety constraints via CodeValidatorService.

    Example:
        llm_client = LLMClient()
        code_validator = CodeValidatorService()
        skill_repo = SkillRepository(session)
        tool_builder = ToolBuilderService(
            llm_client=llm_client,
            code_validator=code_validator,
            skill_repo=skill_repo
        )

        # Generate new tool
        spec = ToolSpecification(
            name="calculate_mean",
            description="Calculate arithmetic mean of numbers",
            input_schema={"numbers": "List[float]"},
            output_schema={"result": "float"}
        )
        generated = await tool_builder.generate_tool(
            spec, improvement_attempt_id="uuid"
        )
    """

    def __init__(
        self,
        llm_client: LLMClient,
        code_validator: CodeValidatorService,
        skill_repo: SkillRepository,
    ):
        """
        Initialize the Tool Builder service.

        Args:
            llm_client: LLMClient for meta-prompting LLM calls.
            code_validator: CodeValidatorService for pre-return validation.
            skill_repo: SkillRepository for persistence.
        """
        self.llm = llm_client
        self.validator = code_validator
        self.skill_repo = skill_repo
        self.log = log

    async def generate_tool(
        self,
        spec: ToolSpecification,
        improvement_attempt_id: str,
    ) -> Skill:
        """
        Generate a new skill from specification.

        Uses meta-prompting to create a Python function with tests
        that meets schema contracts and safety constraints.

        Args:
            spec: ToolSpecification with requirements.
            improvement_attempt_id: UUID linking to improvement attempt.

        Returns:
            Created Skill instance with metadata.

        Raises:
            LLMError: If LLM call fails.
            ValidationError: If LLM output doesn't match schema or code validation fails.
        """
        self.log.info(
            f"Generating skill '{spec.name}' for attempt={improvement_attempt_id[:8]}..."
        )

        try:
            # Build user prompt with specification
            user_prompt = self._build_generation_prompt(spec)

            # Use Instructor for structured output - guarantees valid GeneratedTool
            generated: GeneratedTool = await self.llm.chat_structured(
                messages=[
                    {"role": "system", "content": TOOL_BUILDER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_model=GeneratedTool,
                temperature=0.3,  # Some creativity, mostly structured
                max_retries=3,  # Instructor will retry on validation failures
            )

            self.log.debug(f"Generated tool: {generated.rationale[:100]}...")

            # Validate generated code via CodeValidatorService
            validation_result = self.validator.validate(generated.code)
            if not validation_result.is_valid:
                error_msg = (
                    f"Generated code failed validation: "
                    f"errors={validation_result.errors}, "
                    f"blocked={validation_result.blocked_constructs}"
                )
                self.log.warning(error_msg)
                raise ValidationError.from_exception_data(
                    title="CodeValidationError",
                    line_errors=[
                        {
                            "type": "value_error",
                            "loc": ("code",),
                            "msg": err,
                            "input": generated.code,
                        }
                        for err in validation_result.errors
                    ],
                )

            # Build combined test code for reference
            combined_test_code = self._build_combined_test_code(
                generated.test_cases, spec.name
            )

            # Create Skill record via skill_repo.create()
            skill = await self.skill_repo.create(
                skill_data={
                    "name": spec.name,
                    "description": spec.description,
                    "code": generated.code,
                    "test_cases": [tc.model_dump() for tc in generated.test_cases],
                    "skill_metadata": {
                        "input_schema": spec.input_schema,
                        "output_schema": spec.output_schema,
                        "constraints": spec.constraints,
                        "examples": spec.examples,
                        "imports": generated.imports,
                        "rationale": generated.rationale,
                        "complexity": generated.complexity,
                        "edge_cases_handled": generated.edge_cases_handled,
                        "combined_test_code": combined_test_code,
                        "improvement_attempt_id": improvement_attempt_id,
                    },
                    "is_active": False,  # Not active until A/B tested
                    "parent_id": spec.parent_skill_id,
                }
            )

            self.log.info(
                f"Generated skill id={skill.id}, name={skill.name}, "
                f"tests={len(generated.test_cases)}"
            )

            return skill

        except LLMError as e:
            self.log.warning(f"LLM error during skill generation: {e}")
            raise

        except ValidationError as e:
            self.log.warning(f"Validation error during skill generation: {e}")
            raise

    async def modify_tool(
        self,
        request: ToolModificationRequest,
        improvement_attempt_id: str,
    ) -> Skill:
        """
        Modify an existing skill to address a finding.

        Uses meta-prompting to make surgical changes while preserving
        safety constraints and test coverage.

        Args:
            request: ToolModificationRequest with finding context.
            improvement_attempt_id: UUID linking to improvement attempt.

        Returns:
            New Skill instance (child of original).

        Raises:
            ValueError: If skill not found.
            LLMError: If LLM call fails.
            ValidationError: If LLM output doesn't match schema or code validation fails.
        """
        self.log.info(
            f"Modifying skill {request.skill_id[:8]} for attempt={improvement_attempt_id[:8]}..."
        )

        # Get current skill
        current = await self.skill_repo.get_by_id(request.skill_id)
        if not current:
            raise ValueError(f"Skill not found: {request.skill_id}")

        try:
            # Build user prompt with modification context
            user_prompt = self._build_modification_prompt(current, request)

            # Use Instructor for structured output - guarantees valid ToolModification
            modification: ToolModification = await self.llm.chat_structured(
                messages=[
                    {"role": "system", "content": TOOL_MODIFICATION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_model=ToolModification,
                temperature=0.2,  # More deterministic for modifications
                max_retries=3,  # Instructor will retry on validation failures
            )

            self.log.debug(f"Modified tool: {modification.rationale[:100]}...")

            # Validate modified code via CodeValidatorService
            validation_result = self.validator.validate(modification.modified_code)
            if not validation_result.is_valid:
                error_msg = (
                    f"Modified code failed validation: "
                    f"errors={validation_result.errors}, "
                    f"blocked={validation_result.blocked_constructs}"
                )
                self.log.warning(error_msg)
                raise ValidationError.from_exception_data(
                    title="CodeValidationError",
                    line_errors=[
                        {
                            "type": "value_error",
                            "loc": ("modified_code",),
                            "msg": err,
                            "input": modification.modified_code,
                        }
                        for err in validation_result.errors
                    ],
                )

            # Build combined test code for reference
            combined_test_code = self._build_combined_test_code(
                modification.modified_tests, current.name
            )

            # Create new skill version as child of original
            new_skill = await self.skill_repo.create(
                skill_data={
                    "name": current.name,  # Same name, new version
                    "description": current.description,
                    "code": modification.modified_code,
                    "test_cases": [tc.model_dump() for tc in modification.modified_tests],
                    "skill_metadata": {
                        **current.skill_metadata,  # Preserve parent metadata
                        "modification_rationale": modification.rationale,
                        "changes_made": modification.changes_made,
                        "finding_addressed": request.finding_description,
                        "combined_test_code": combined_test_code,
                        "improvement_attempt_id": improvement_attempt_id,
                    },
                    "is_active": False,  # Not active until A/B tested
                    "parent_id": current.id,  # Link to parent
                }
            )

            self.log.info(
                f"Modified skill id={new_skill.id}, parent_id={current.id[:8]}, "
                f"changes={len(modification.changes_made)}"
            )

            return new_skill

        except LLMError as e:
            self.log.warning(f"LLM error during skill modification: {e}")
            raise

        except ValidationError as e:
            self.log.warning(f"Validation error during skill modification: {e}")
            raise

    def _build_generation_prompt(self, spec: ToolSpecification) -> str:
        """
        Build user prompt for generation.

        Args:
            spec: ToolSpecification with requirements.

        Returns:
            Formatted prompt string for the LLM.
        """
        lines = ["## Skill Name", ""]
        lines.append(spec.name)
        lines.append("")

        lines.append("## Description")
        lines.append("")
        lines.append(spec.description)
        lines.append("")

        lines.append("## Input Schema")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(spec.input_schema, indent=2))
        lines.append("```")
        lines.append("")

        lines.append("## Output Schema")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(spec.output_schema, indent=2))
        lines.append("```")
        lines.append("")

        if spec.constraints:
            lines.append("## Constraints")
            lines.append("")
            for constraint in spec.constraints:
                lines.append(f"- {constraint}")
            lines.append("")

        if spec.examples:
            lines.append("## Examples")
            lines.append("")
            for i, example in enumerate(spec.examples, 1):
                lines.append(f"**Example {i}:**")
                lines.append("```json")
                lines.append(json.dumps(example, indent=2))
                lines.append("```")
                lines.append("")

        lines.append("## Instructions")
        lines.append("")
        lines.append(
            "Generate a Python function that meets these requirements. "
            "Include comprehensive type hints, docstring, input validation, "
            "and error handling. Also generate pytest test cases covering "
            "basic functionality, edge cases, and error conditions."
        )

        return "\n".join(lines)

    def _build_modification_prompt(
        self,
        current: Skill,
        request: ToolModificationRequest,
    ) -> str:
        """
        Build user prompt for modification.

        Args:
            current: Current Skill instance.
            request: ToolModificationRequest with finding context.

        Returns:
            Formatted prompt string for the LLM.
        """
        lines = ["## Current Skill Code", ""]
        lines.append("```python")
        lines.append(current.code)
        lines.append("```")
        lines.append("")

        lines.append("## Current Tests")
        lines.append("")
        for tc in current.test_cases:
            lines.append(f"### {tc.get('name', 'test')}")
            lines.append("```python")
            lines.append(tc.get("test_code", ""))
            lines.append("```")
            lines.append("")

        lines.append("## Issue to Address")
        lines.append("")
        lines.append(request.finding_description)
        lines.append("")

        lines.append("## Improvement Direction")
        lines.append("")
        lines.append(request.improvement_direction)
        lines.append("")

        lines.append("## Instructions")
        lines.append("")
        lines.append(
            "Modify the skill to address the issue. Make the smallest change "
            "necessary. Update tests as needed to verify the fix. "
            "Maintain all safety constraints and input validation."
        )

        return "\n".join(lines)

    def _build_combined_test_code(
        self,
        test_cases: list[TestCase],
        function_name: str,
    ) -> str:
        """
        Combine all test cases into single pytest file.

        Args:
            test_cases: List of TestCase instances.
            function_name: Name of the function being tested.

        Returns:
            Combined pytest file content.
        """
        lines = ["import pytest", f"from skill import {function_name}", ""]

        for tc in test_cases:
            # Handle both TestCase objects and dicts
            if hasattr(tc, "test_code"):
                lines.append(tc.test_code)
            else:
                lines.append(tc.get("test_code", ""))
            lines.append("")

        return "\n".join(lines)
