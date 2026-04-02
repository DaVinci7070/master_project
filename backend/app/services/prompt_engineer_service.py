"""
Prompt Engineer Service for generating and modifying prompts.

This service implements the Prompt Engineer agent that can:
- Generate new prompts from natural language requirements
- Modify existing prompts to address identified issues
- Validate schema compliance for all changes
- Track rationale and version history via parent-child relationships

Flow:
    ControlAgent decides improvement -> PromptEngineerService.generate/modify()
    -> New prompt version created -> A/B testing validates -> Promote or rollback
"""
import json
import logging
from typing import Optional

from pydantic import ValidationError

from app.core.llm_client import LLMClient, LLMError
from app.models.schemas.prompt_engineer_schemas import (
    PromptGenerationRequest,
    PromptModificationRequest,
    GeneratedPrompt,
    PromptModification,
)
from app.models.sql.versioned_models import Prompt
from app.repositories.prompt_repository import PromptRepository
from app.prompts.prompt_engineer_prompt import (
    PROMPT_ENGINEER_SYSTEM_PROMPT,
    PROMPT_MODIFICATION_SYSTEM_PROMPT,
)

log = logging.getLogger(__name__)


class PromptEngineerService:
    """
    Prompt Engineer: generates and modifies prompts via meta-prompting.

    Uses LLM meta-prompting with structured output to create/modify prompts
    while enforcing schema contracts and tracking version history.

    Example:
        llm_client = LLMClient()
        prompt_repo = PromptRepository(session)
        prompt_engineer = PromptEngineerService(
            llm_client=llm_client,
            prompt_repo=prompt_repo
        )

        # Generate new prompt
        request = PromptGenerationRequest(
            name="analyzer_prompt",
            purpose="Analyze telemetry for quality issues",
            input_schema={...},
            output_schema={...}
        )
        new_prompt = await prompt_engineer.generate_prompt(
            request, improvement_attempt_id="uuid"
        )

        # Modify existing prompt
        mod_request = PromptModificationRequest(
            prompt_id=existing_prompt_id,
            finding_description="Output too verbose",
            improvement_direction="Make output more concise"
        )
        modified_prompt = await prompt_engineer.modify_prompt(
            mod_request, improvement_attempt_id="uuid"
        )
    """

    def __init__(self, llm_client: LLMClient, prompt_repo: PromptRepository):
        """
        Initialize the Prompt Engineer service.

        Args:
            llm_client: LLMClient for meta-prompting LLM calls.
            prompt_repo: PromptRepository for persistence.
        """
        self.llm = llm_client
        self.prompt_repo = prompt_repo
        self.log = log

    async def generate_prompt(
        self,
        request: PromptGenerationRequest,
        improvement_attempt_id: str,
    ) -> Prompt:
        """
        Generate a new prompt from requirements.

        Uses meta-prompting to create a structured prompt that meets
        input/output schema contracts.

        Args:
            request: PromptGenerationRequest with requirements.
            improvement_attempt_id: UUID linking to improvement attempt.

        Returns:
            Created Prompt instance with metadata.

        Raises:
            LLMError: If LLM call fails.
            ValidationError: If LLM output doesn't match schema.
        """
        log.info(
            f"Generating prompt '{request.name}' for attempt={improvement_attempt_id[:8]}..."
        )

        try:
            # Build user prompt with requirements
            user_prompt = self._build_generation_prompt(request)

            # Build JSON schema for structured output
            json_schema = self._build_generation_schema()

            # Call LLM with meta-prompting
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": PROMPT_ENGINEER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,  # Some creativity, mostly structured
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "generated_prompt",
                        "strict": True,
                        "schema": json_schema,
                    },
                },
            )

            log.debug(f"LLM response: {response.content[:200]}...")

            # Parse and validate the response
            generated = GeneratedPrompt.model_validate_json(response.content)

            # Create prompt record with metadata
            prompt = await self.prompt_repo.create(
                name=request.name,
                content=generated.content,
                parent_id=request.parent_prompt_id,
                prompt_metadata={
                    "purpose": request.purpose,
                    "input_schema": request.input_schema,
                    "output_schema": request.output_schema,
                    "constraints": request.constraints,
                    "sections": generated.sections,
                    "input_variables": generated.input_variables,
                    "generation_rationale": generated.rationale,
                    "improvement_attempt_id": improvement_attempt_id,
                },
            )

            log.info(
                f"Generated prompt id={prompt.id}, sections={len(generated.sections)}"
            )

            return prompt

        except LLMError as e:
            log.warning(f"LLM error during prompt generation: {e}")
            raise

        except ValidationError as e:
            log.warning(f"Validation error parsing generated prompt: {e}")
            raise

    async def modify_prompt(
        self,
        request: PromptModificationRequest,
        improvement_attempt_id: str,
    ) -> Prompt:
        """
        Modify an existing prompt to address a finding.

        Uses meta-prompting to make surgical changes while preserving
        schema contracts and specified sections.

        Args:
            request: PromptModificationRequest with finding context.
            improvement_attempt_id: UUID linking to improvement attempt.

        Returns:
            New Prompt instance (child of original).

        Raises:
            ValueError: If prompt not found.
            LLMError: If LLM call fails.
            ValidationError: If LLM output doesn't match schema.
        """
        log.info(
            f"Modifying prompt {request.prompt_id[:8]} for attempt={improvement_attempt_id[:8]}..."
        )

        # Get current prompt
        current = await self.prompt_repo.get_by_id(request.prompt_id)
        if not current:
            raise ValueError(f"Prompt not found: {request.prompt_id}")

        try:
            # Extract output schema from metadata for validation
            output_schema = current.prompt_metadata.get("output_schema", {})

            # Build user prompt with modification context
            user_prompt = self._build_modification_prompt(
                current.content,
                request.finding_description,
                request.improvement_direction,
                output_schema,
                request.preserve_sections,
            )

            # Build JSON schema for structured output
            json_schema = self._build_modification_schema()

            # Call LLM with modification meta-prompt
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": PROMPT_MODIFICATION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,  # More deterministic for modifications
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "prompt_modification",
                        "strict": True,
                        "schema": json_schema,
                    },
                },
            )

            log.debug(f"LLM response: {response.content[:200]}...")

            # Parse and validate the response
            modification = PromptModification.model_validate_json(response.content)

            # Warn if schema impact is not "none"
            if modification.schema_impact.lower() != "none":
                log.warning(
                    f"Prompt modification has schema impact: {modification.schema_impact}"
                )

            # Create new version as child of current
            new_prompt = await self.prompt_repo.create(
                name=current.name,  # Same name, new version
                content=modification.modified_content,
                parent_id=current.id,  # Link to parent
                prompt_metadata={
                    **current.prompt_metadata,  # Preserve parent metadata
                    "modification_rationale": modification.rationale,
                    "changes_made": modification.changes_made,
                    "sections_modified": modification.sections_modified,
                    "finding_addressed": request.finding_description,
                    "improvement_attempt_id": improvement_attempt_id,
                },
            )

            log.info(
                f"Modified prompt id={new_prompt.id}, parent_id={current.id[:8]}, "
                f"changes={len(modification.changes_made)}"
            )

            return new_prompt

        except LLMError as e:
            log.warning(f"LLM error during prompt modification: {e}")
            raise

        except ValidationError as e:
            log.warning(f"Validation error parsing prompt modification: {e}")
            raise

    def _build_generation_prompt(self, request: PromptGenerationRequest) -> str:
        """
        Build user prompt for generation.

        Args:
            request: PromptGenerationRequest with requirements.

        Returns:
            Formatted prompt string for the LLM.
        """
        lines = ["## Requirements", ""]
        lines.append(f"**Prompt Name**: {request.name}")
        lines.append(f"**Purpose**: {request.purpose}")
        lines.append("")

        lines.append("## Input Schema")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(request.input_schema, indent=2))
        lines.append("```")
        lines.append("")

        lines.append("## Output Schema")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(request.output_schema, indent=2))
        lines.append("```")
        lines.append("")

        if request.constraints:
            lines.append("## Constraints")
            lines.append("")
            for constraint in request.constraints:
                lines.append(f"- {constraint}")
            lines.append("")

        if request.examples:
            lines.append("## Examples")
            lines.append("")
            for i, example in enumerate(request.examples, 1):
                lines.append(f"**Example {i}:**")
                lines.append("```json")
                lines.append(json.dumps(example, indent=2))
                lines.append("```")
                lines.append("")

        lines.append("## Instructions")
        lines.append("")
        lines.append(
            "Generate a prompt that meets these requirements. "
            "The prompt must guide an LLM agent to produce output matching "
            "the Output Schema exactly. Include clear role definition, guidelines, "
            "and output format specifications."
        )

        return "\n".join(lines)

    def _build_modification_prompt(
        self,
        current_content: str,
        finding: str,
        direction: str,
        output_schema: dict,
        preserve_sections: list[str],
    ) -> str:
        """
        Build user prompt for modification.

        Args:
            current_content: Current prompt text.
            finding: Issue identified.
            direction: Improvement direction.
            output_schema: Schema that must be preserved.
            preserve_sections: Sections that must not change.

        Returns:
            Formatted prompt string for the LLM.
        """
        lines = ["## Current Prompt", ""]
        lines.append("```markdown")
        lines.append(current_content)
        lines.append("```")
        lines.append("")

        lines.append("## Issue to Address")
        lines.append("")
        lines.append(finding)
        lines.append("")

        lines.append("## Improvement Direction")
        lines.append("")
        lines.append(direction)
        lines.append("")

        lines.append("## Output Schema (MUST PRESERVE)")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(output_schema, indent=2))
        lines.append("```")
        lines.append("")

        if preserve_sections:
            lines.append("## Sections That MUST NOT Change")
            lines.append("")
            for section in preserve_sections:
                lines.append(f"- {section}")
            lines.append("")

        lines.append("## Instructions")
        lines.append("")
        lines.append(
            "Modify the current prompt to address the issue while preserving "
            "the output schema. Make the smallest change necessary. "
            "Return the complete modified prompt with your changes."
        )

        return "\n".join(lines)

    def _build_generation_schema(self) -> dict:
        """
        Build JSON schema for GeneratedPrompt.

        Returns:
            JSON Schema dict for response_format.
        """
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "minLength": 100,
                    "description": "The generated prompt text",
                },
                "sections": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Logical sections in the prompt",
                },
                "input_variables": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Variables that need runtime substitution",
                },
                "rationale": {
                    "type": "string",
                    "minLength": 20,
                    "description": "Explanation of design decisions",
                },
            },
            "required": ["content", "sections", "input_variables", "rationale"],
            "additionalProperties": False,
        }

    def _build_modification_schema(self) -> dict:
        """
        Build JSON schema for PromptModification.

        Returns:
            JSON Schema dict for response_format.
        """
        return {
            "type": "object",
            "properties": {
                "modified_content": {
                    "type": "string",
                    "minLength": 100,
                    "description": "Updated prompt text",
                },
                "changes_made": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of specific changes",
                },
                "sections_modified": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Which sections were changed",
                },
                "rationale": {
                    "type": "string",
                    "minLength": 20,
                    "description": "Why these changes address the finding",
                },
                "schema_impact": {
                    "type": "string",
                    "description": "How output schema is affected - should be 'none'",
                },
            },
            "required": [
                "modified_content",
                "changes_made",
                "sections_modified",
                "rationale",
                "schema_impact",
            ],
            "additionalProperties": False,
        }
