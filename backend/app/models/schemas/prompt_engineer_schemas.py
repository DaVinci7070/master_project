"""
Pydantic schemas for Prompt Engineer operations.

These schemas handle validation for:
- Prompt generation requests (PromptGenerationRequest, GeneratedPrompt)
- Prompt modification requests (PromptModificationRequest, PromptModification)
- Meta-prompting LLM input/output with schema contracts
"""
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class PromptGenerationRequest(BaseModel):
    """
    Schema for requesting a new prompt generation.

    Used by PromptEngineerService to create prompts from natural language
    requirements with schema contracts.
    """
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Prompt identifier"
    )
    purpose: str = Field(
        ...,
        min_length=20,
        description="What the prompt should accomplish"
    )
    input_schema: dict = Field(
        ...,
        description="Expected input structure as JSON Schema"
    )
    output_schema: dict = Field(
        ...,
        description="Expected output structure as JSON Schema"
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Hard constraints to enforce"
    )
    examples: list[dict] = Field(
        default_factory=list,
        description="Example input/output pairs"
    )
    parent_prompt_id: Optional[str] = Field(
        None,
        min_length=36,
        max_length=36,
        description="Base prompt to derive from"
    )


class PromptModificationRequest(BaseModel):
    """
    Schema for requesting modification of an existing prompt.

    Captures finding context and preservation constraints to guide
    schema-aware modification.
    """
    prompt_id: str = Field(
        ...,
        min_length=36,
        max_length=36,
        description="UUID of prompt to modify"
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
    preserve_sections: list[str] = Field(
        default_factory=list,
        description="Sections that must not change"
    )


class GeneratedPrompt(BaseModel):
    """
    LLM output schema for prompt generation.

    Structured output from meta-prompting LLM call when generating
    a new prompt.
    """
    content: str = Field(
        ...,
        min_length=100,
        description="The generated prompt text"
    )
    sections: list[str] = Field(
        ...,
        description="Logical sections in the prompt"
    )
    input_variables: list[str] = Field(
        ...,
        description="Variables that need runtime substitution"
    )
    rationale: str = Field(
        ...,
        min_length=20,
        description="Explanation of design decisions"
    )


class PromptModification(BaseModel):
    """
    LLM output schema for prompt modification.

    Structured output from meta-prompting LLM call when modifying
    an existing prompt to address a finding.
    """
    modified_content: str = Field(
        ...,
        min_length=100,
        description="Updated prompt text"
    )
    changes_made: list[str] = Field(
        ...,
        description="List of specific changes"
    )
    sections_modified: list[str] = Field(
        ...,
        description="Which sections were changed"
    )
    rationale: str = Field(
        ...,
        min_length=20,
        description="Why these changes address the finding"
    )
    schema_impact: str = Field(
        ...,
        description="How output schema is affected - should be 'none'"
    )
