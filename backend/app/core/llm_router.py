"""
LLM Router - Task-specific model routing for skill development.

Routes different tasks to appropriate models:
- Research: Fast model for broad search
- Architecture: Strong model for design decisions
- Implementation: Fast model for iteration
- Review: Strong model for quality checks
"""

import logging
import os
from enum import Enum
from typing import Optional

from app.core.llm_client import LLMClient

log = logging.getLogger(__name__)


class TaskType(str, Enum):
    """Types of tasks for LLM routing."""
    RESEARCH = "research"
    ARCHITECTURE = "architecture"
    IMPLEMENTATION = "implementation"
    REVIEW = "review"
    CODE_FIX = "code_fix"
    SEMANTIC_VALIDATION = "semantic_validation"
    GENERAL = "general"


# Default model assignments per task type
# These can be overridden via environment variables
DEFAULT_TASK_MODELS = {
    TaskType.RESEARCH: "gemini/gemini-2.0-flash",  # Fast for research
    TaskType.ARCHITECTURE: "gemini/gemini-3-flash-preview",  # Strong for design
    TaskType.IMPLEMENTATION: "gemini/gemini-3-flash-preview",  # Strong for code generation
    TaskType.REVIEW: "gemini/gemini-3-flash-preview",  # Strong for review
    TaskType.CODE_FIX: "gemini/gemini-2.0-flash",  # Fast for fixes
    TaskType.SEMANTIC_VALIDATION: "gemini/gemini-3-flash-preview",  # Strong for validation
    TaskType.GENERAL: "gemini/gemini-2.0-flash",  # Default
}

# Environment variable names for model overrides
ENV_MODEL_OVERRIDES = {
    TaskType.RESEARCH: "SKILL_RESEARCHER_MODEL",
    TaskType.ARCHITECTURE: "SKILL_ARCHITECT_MODEL",
    TaskType.IMPLEMENTATION: "SKILL_IMPLEMENTER_MODEL",
    TaskType.REVIEW: "SKILL_REVIEWER_MODEL",
    TaskType.CODE_FIX: "SKILL_CODEFIX_MODEL",
    TaskType.SEMANTIC_VALIDATION: "SKILL_SEMANTIC_MODEL",
    TaskType.GENERAL: "LLM_MODEL",
}


class LLMRouter:
    """
    Routes tasks to appropriate LLM models.

    Uses a tiered approach:
    - Fast models (Gemini Flash) for iterative tasks like research, implementation
    - Strong models (Claude Sonnet) for critical tasks like architecture, review

    Model assignments can be overridden via environment variables.
    """

    def __init__(
        self,
        default_model: Optional[str] = None,
        model_overrides: Optional[dict[TaskType, str]] = None,
    ):
        """
        Initialize the LLM router.

        Args:
            default_model: Default model if no task-specific model is configured
            model_overrides: Dictionary of task type -> model name overrides
        """
        self._default_model = default_model or os.getenv(
            "LLM_MODEL", "gemini/gemini-2.0-flash"
        )
        self._model_overrides = model_overrides or {}
        self._task_models = self._build_task_models()
        self._llm_clients: dict[str, LLMClient] = {}

        log.info(f"LLM Router initialized with models: {self._task_models}")

    def _build_task_models(self) -> dict[TaskType, str]:
        """Build task model mapping from defaults, env, and overrides."""
        task_models = {}

        for task_type in TaskType:
            # Priority: override > env > default
            if task_type in self._model_overrides:
                model = self._model_overrides[task_type]
            else:
                env_var = ENV_MODEL_OVERRIDES.get(task_type)
                env_model = os.getenv(env_var) if env_var else None
                model = env_model or DEFAULT_TASK_MODELS.get(task_type, self._default_model)

            task_models[task_type] = model

        return task_models

    def get_model(self, task_type: TaskType) -> str:
        """Get the model name for a specific task type."""
        return self._task_models.get(task_type, self._default_model)

    def get_client(self, task_type: TaskType) -> LLMClient:
        """
        Get an LLM client configured for a specific task type.

        Clients are cached for reuse.

        Args:
            task_type: The type of task

        Returns:
            LLMClient configured with the appropriate model
        """
        model = self.get_model(task_type)

        if model not in self._llm_clients:
            self._llm_clients[model] = LLMClient(model=model)
            log.debug(f"Created LLM client for model: {model}")

        return self._llm_clients[model]

    def get_research_client(self) -> LLMClient:
        """Get client for research tasks."""
        return self.get_client(TaskType.RESEARCH)

    def get_architecture_client(self) -> LLMClient:
        """Get client for architecture tasks."""
        return self.get_client(TaskType.ARCHITECTURE)

    def get_implementation_client(self) -> LLMClient:
        """Get client for implementation tasks."""
        return self.get_client(TaskType.IMPLEMENTATION)

    def get_review_client(self) -> LLMClient:
        """Get client for review tasks."""
        return self.get_client(TaskType.REVIEW)

    def get_codefix_client(self) -> LLMClient:
        """Get client for code fixing tasks."""
        return self.get_client(TaskType.CODE_FIX)

    def get_semantic_client(self) -> LLMClient:
        """Get client for semantic validation."""
        return self.get_client(TaskType.SEMANTIC_VALIDATION)

    def update_model(self, task_type: TaskType, model: str) -> None:
        """
        Update the model for a task type at runtime.

        Args:
            task_type: The task type to update
            model: New model name
        """
        self._task_models[task_type] = model
        log.info(f"Updated model for {task_type.value}: {model}")

    def get_all_models(self) -> dict[str, str]:
        """Get all task type -> model mappings."""
        return {t.value: m for t, m in self._task_models.items()}


# Global router instance
_router: Optional[LLMRouter] = None


def get_router() -> LLMRouter:
    """Get the global LLM router instance."""
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router


def get_client_for_task(task_type: TaskType) -> LLMClient:
    """Convenience function to get LLM client for a task type."""
    return get_router().get_client(task_type)


# Model characteristics for reference
MODEL_CHARACTERISTICS = {
    "gemini/gemini-2.0-flash": {
        "provider": "google",
        "strengths": ["speed", "cost-efficiency", "large context"],
        "weaknesses": ["complex reasoning", "subtle bugs"],
        "best_for": ["research", "first-pass implementation", "simple fixes"],
        "cost_tier": "low",
    },
    "claude-3-5-sonnet-20241022": {
        "provider": "anthropic",
        "strengths": ["code quality", "reasoning", "bug detection"],
        "weaknesses": ["speed", "cost"],
        "best_for": ["architecture", "review", "complex debugging"],
        "cost_tier": "medium",
    },
    "gpt-4o": {
        "provider": "openai",
        "strengths": ["versatility", "coding", "reasoning"],
        "weaknesses": ["cost", "rate limits"],
        "best_for": ["general tasks", "complex problems"],
        "cost_tier": "medium",
    },
    "gpt-4o-mini": {
        "provider": "openai",
        "strengths": ["speed", "cost-efficiency"],
        "weaknesses": ["complex reasoning"],
        "best_for": ["simple tasks", "iteration"],
        "cost_tier": "low",
    },
}


def get_model_info(model: str) -> dict:
    """Get characteristics of a model."""
    return MODEL_CHARACTERISTICS.get(model, {
        "provider": "unknown",
        "strengths": [],
        "weaknesses": [],
        "best_for": [],
        "cost_tier": "unknown",
    })
