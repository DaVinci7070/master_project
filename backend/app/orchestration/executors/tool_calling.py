"""
Tool Calling support for GenericAgentExecutor.

Enables agents to call skills during execution using structured JSON output
validated by Instructor/Pydantic.

Design decisions:
- JSON + Instructor for provider-agnostic, validated outputs
- SandboxExecutorService for secure execution
- Max 5 tool calls per agent run
"""
import json
import logging
from typing import Any, Optional, Union, Literal
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Maximum tool calls per agent execution to prevent infinite loops
MAX_TOOL_CALLS = 5


class ToolCallRequest(BaseModel):
    """Request to call a tool/skill."""
    thought: str = Field(
        ...,
        description="Reasoning for why this tool is needed"
    )
    action: Literal["tool_call"] = Field(
        default="tool_call",
        description="Action type - must be 'tool_call'"
    )
    tool: str = Field(
        ...,
        description="Name of the tool/skill to call"
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments to pass to the tool"
    )


class FinalAnswer(BaseModel):
    """Final response when no more tools are needed."""
    thought: Optional[str] = Field(
        None,
        description="Final reasoning"
    )
    action: Literal["final_answer"] = Field(
        default="final_answer",
        description="Action type - must be 'final_answer'"
    )
    response: str = Field(
        ...,
        description="The final answer/response"
    )


class AgentResponse(BaseModel):
    """Union type for agent responses - either a tool call or final answer."""
    thought: Optional[str] = Field(None, description="Agent's reasoning")
    action: Literal["tool_call", "final_answer"] = Field(
        ...,
        description="Whether this is a tool call or final answer"
    )
    # Tool call fields (optional)
    tool: Optional[str] = Field(None, description="Tool name if action=tool_call")
    arguments: Optional[dict[str, Any]] = Field(None, description="Tool arguments if action=tool_call")
    # Final answer fields (optional)
    response: Optional[str] = Field(None, description="Final response if action=final_answer")

    def is_tool_call(self) -> bool:
        """Check if this is a tool call."""
        return self.action == "tool_call"

    def is_final_answer(self) -> bool:
        """Check if this is a final answer."""
        return self.action == "final_answer"

    def to_tool_call(self) -> Optional[ToolCallRequest]:
        """Convert to ToolCallRequest if this is a tool call."""
        if not self.is_tool_call() or not self.tool:
            return None
        return ToolCallRequest(
            thought=self.thought or "",
            action="tool_call",
            tool=self.tool,
            arguments=self.arguments or {}
        )


class ToolResult(BaseModel):
    """Result of executing a tool/skill."""
    tool: str = Field(..., description="Name of the tool that was called")
    success: bool = Field(..., description="Whether execution succeeded")
    output: Optional[Any] = Field(None, description="Tool output if successful")
    error: Optional[str] = Field(None, description="Error message if failed")
    execution_time_ms: float = Field(0.0, description="Execution time in milliseconds")


class ToolCallDetector:
    """
    Detects and parses tool calls from LLM output.

    Supports both structured (Instructor) and unstructured (JSON parsing) modes.
    """

    def detect_from_text(self, text: str) -> Optional[AgentResponse]:
        """
        Try to parse an AgentResponse from raw text.

        Handles cases where LLM returns JSON in markdown code blocks.
        Only parses if the JSON looks like a tool call (has 'action' field).

        Args:
            text: Raw LLM output text

        Returns:
            AgentResponse if valid tool call/final answer JSON found, None otherwise
        """
        # Quick check - only try to parse if it looks like a tool call
        if not self.is_likely_tool_call(text):
            return None

        # Try to extract JSON from text
        json_str = self._extract_json(text)
        if not json_str:
            return None

        try:
            data = json.loads(json_str)
            # Only parse as AgentResponse if it has the action field
            if "action" not in data:
                return None
            return AgentResponse(**data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug(f"Failed to parse tool call from text: {e}")
            return None

    def _extract_json(self, text: str) -> Optional[str]:
        """Extract JSON from text, handling markdown code blocks."""
        text = text.strip()

        # Try direct JSON parse first
        if text.startswith("{"):
            # Find matching closing brace
            brace_count = 0
            for i, char in enumerate(text):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        return text[:i+1]
            return text  # Return whole text if no matching brace found

        # Try extracting from markdown code block
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                return text[start:end].strip()

        if "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            if end > start:
                content = text[start:end].strip()
                if content.startswith("{"):
                    return content

        return None

    def is_likely_tool_call(self, text: str) -> bool:
        """Quick check if text might contain a tool call or final answer."""
        has_action = '"action"' in text
        has_tool_call = '"tool_call"' in text
        has_final_answer = '"final_answer"' in text
        return has_action and (has_tool_call or has_final_answer)


def build_tool_prompt_section(skills: list[dict[str, Any]]) -> str:
    """
    Build the tool documentation section for agent prompts.

    Args:
        skills: List of skill dicts with name, description, and optional parameters

    Returns:
        Formatted prompt section explaining available tools
    """
    if not skills:
        return ""

    tool_docs = []
    for skill in skills:
        name = skill.get("name", "unknown")
        description = skill.get("description", "No description")
        params = skill.get("parameters", {})

        # Build parameter signature
        param_sig = ""
        if params:
            param_parts = []
            for param_name, param_info in params.items():
                param_type = param_info.get("type", "any") if isinstance(param_info, dict) else "any"
                param_parts.append(f"{param_name}: {param_type}")
            param_sig = ", ".join(param_parts)

        tool_docs.append(f"- **{name}**({param_sig})\n  {description}")

    return f"""
## Available Tools

You have access to the following tools. To use a tool, respond with this EXACT JSON format:

```json
{{
  "thought": "Brief reason for tool choice (1-2 sentences max)",
  "action": "tool_call",
  "tool": "<tool_name>",
  "arguments": {{
    "param1": value1,
    "param2": value2
  }}
}}
```

When you have the final answer and no more tools are needed, respond with:

```json
{{
  "thought": "Brief summary (1-2 sentences)",
  "action": "final_answer",
  "response": "Your complete final answer here"
}}
```

CRITICAL RULES:
1. Keep "thought" VERY SHORT (1-2 sentences). Do NOT include analysis or data extraction in thought.
2. Always respond with ONLY valid JSON. No text outside the JSON block.
3. Put all detailed analysis in "response" field for final_answer, NOT in "thought".
4. Extract data from input and pass it directly as tool arguments.

### Available Tools:
{chr(10).join(tool_docs)}
"""


def format_tool_result_for_llm(result: ToolResult) -> str:
    """
    Format a tool result for inclusion in LLM conversation.

    Args:
        result: The ToolResult from skill execution

    Returns:
        Formatted string for LLM context
    """
    if result.success:
        output_str = json.dumps(result.output, indent=2, default=str) if result.output else "null"
        return f"""Tool '{result.tool}' executed successfully in {result.execution_time_ms:.1f}ms.

Result:
```json
{output_str}
```

Now analyze this result and either call another tool or provide your final answer."""
    else:
        return f"""Tool '{result.tool}' failed with error: {result.error}

Execution time: {result.execution_time_ms:.1f}ms

Please handle this error appropriately - either try a different approach or explain the issue in your final answer."""
