import json
from typing import Any, Dict, List


TASK_DECOMPOSITION_SYSTEM_PROMPT = """You are a task decomposition specialist for a multi-agent coding system.

Your job is to analyze complex development tasks and break them into file-level subtasks that can be executed by parallel coding agents.

## Decomposition Rules

1. **One File Per Agent**: Each subtask targets exactly one file. Agents cannot modify multiple files.

2. **Maximum 10 Files**: Never decompose into more than 10 subtasks. If more files needed, identify the 10 most critical.

3. **Execution Waves**: Group subtasks into parallel waves:
   - Wave 1: Files with no dependencies (can run immediately)
   - Wave 2: Files that depend only on Wave 1 outputs
   - Wave 3+: Files with deeper dependencies

4. **Interface Contracts**: For each file, define:
   - What functions/classes it must export
   - Expected type signatures
   - Dependencies it can import

5. **Minimize Dependencies**: Prefer designs where files are independent. High coupling = sequential execution = slow.

## Output Format

You MUST respond with valid JSON matching this schema:

```json
{
  "subtasks": [
    {
      "file_path": "path/to/file.py",
      "task_description": "What this file should implement",
      "required_files": ["paths to dependencies"],
      "interface_contract": {
        "exports": ["function_name: (params) -> return_type"],
        "imports_from": ["module.path"]
      },
      "estimated_complexity": "simple|moderate|complex",
      "depends_on": ["file paths that must complete first"]
    }
  ],
  "execution_order": [
    ["wave1_file1.py", "wave1_file2.py"],
    ["wave2_file1.py"],
    ["wave3_file1.py"]
  ],
  "shared_context": {
    "key": "value"
  },
  "rationale": "Why this decomposition strategy"
}
```

## Quality Checks

Before outputting, verify:
- [ ] No more than 10 subtasks
- [ ] Every file has a clear task_description
- [ ] Interface contracts are specific (not vague)
- [ ] Execution order respects depends_on relationships
- [ ] No circular dependencies
"""


TASK_DECOMPOSITION_USER_TEMPLATE = """## Development Task

**Description**: {description}

**Files to Create/Modify**:
{files_list}

**Existing Context Files** (read-only reference):
{context_files}

**Constraints**:
{constraints}

## Instructions

Analyze this task and decompose it into file-level subtasks. Consider:
1. Which files can be built independently (Wave 1)?
2. Which files depend on others?
3. What are the interface contracts between files?
4. How to minimize coupling for maximum parallelism?

Respond with valid JSON as specified in the system prompt.
"""


def build_decomposition_prompt(
    description: str,
    files_involved: List[str],
    context_files: List[str],
    constraints: List[str],
) -> str:
    """
    Build user prompt for task decomposition.

    Args:
        description: Natural language description of the task.
        files_involved: List of files to create/modify.
        context_files: Existing files for reference (read-only).
        constraints: Requirements or limitations.

    Returns:
        Formatted user prompt string.
    """
    files_list = "\n".join(f"- {f}" for f in files_involved) if files_involved else "- None specified"
    context_list = "\n".join(f"- {f}" for f in context_files) if context_files else "- None"
    constraints_list = "\n".join(f"- {c}" for c in constraints) if constraints else "- None"

    return TASK_DECOMPOSITION_USER_TEMPLATE.format(
        description=description,
        files_list=files_list,
        context_files=context_list,
        constraints=constraints_list,
    )


def build_decomposition_schema() -> Dict[str, Any]:
    """
    Build JSON schema for task decomposition output.

    Returns:
        JSON Schema dict for response_format.
    """
    return {
        "type": "object",
        "properties": {
            "subtasks": {
                "type": "array",
                "minItems": 1,
                "maxItems": 10,
                "items": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Path to file to create/modify",
                        },
                        "task_description": {
                            "type": "string",
                            "minLength": 10,
                            "description": "What this subtask accomplishes",
                        },
                        "required_files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Files this subtask needs to read",
                        },
                        "interface_contract": {
                            "type": "object",
                            "description": "Expected exports and imports",
                        },
                        "estimated_complexity": {
                            "type": "string",
                            "enum": ["simple", "moderate", "complex"],
                            "description": "Task complexity estimate",
                        },
                        "depends_on": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "File paths that must complete first",
                        },
                    },
                    "required": [
                        "file_path",
                        "task_description",
                        "required_files",
                        "interface_contract",
                        "estimated_complexity",
                        "depends_on",
                    ],
                    "additionalProperties": False,
                },
            },
            "execution_order": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "description": "Parallel execution waves",
            },
            "shared_context": {
                "type": "object",
                "description": "Context shared across all subtasks",
            },
            "rationale": {
                "type": "string",
                "minLength": 20,
                "description": "Why this decomposition strategy",
            },
        },
        "required": ["subtasks", "execution_order", "shared_context", "rationale"],
        "additionalProperties": False,
    }
