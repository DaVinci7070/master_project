"""Context budget management for LLM context window allocation."""
import tiktoken
from typing import Any


class ContextBudgetManager:
    """Manage LLM context window budget with token counting."""

    def __init__(
        self,
        model: str = "gpt-4o",
        target_items: int = 50,
        max_items: int = 70
    ):
        """
        Initialize context budget manager.

        Args:
            model: Model name for tiktoken encoding selection
            target_items: Soft limit on items (CONTEXT: 30-50)
            max_items: Hard limit on items (CONTEXT: up to 70)
        """
        self.encoding = tiktoken.encoding_for_model(model)
        self.target_items = target_items
        self.max_items = max_items

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self.encoding.encode(text))

    def truncate_with_budget(
        self,
        items: list[dict[str, Any]],
        max_tokens: int,
        key: str = "text"
    ) -> list[dict]:
        """
        Truncate items to fit context budget.
        Items should be pre-sorted by relevance (highest first).

        Args:
            items: List of dicts with text content
            max_tokens: Maximum total tokens allowed
            key: Key containing text to measure

        Returns:
            Filtered list fitting within budget
        """
        selected = []
        total_tokens = 0

        for item in items:
            text = item.get(key, "")
            tokens = self.count_tokens(str(text))

            # Soft limit: try to stay under target_items
            if len(selected) < self.target_items:
                if total_tokens + tokens <= max_tokens:
                    selected.append(item)
                    total_tokens += tokens
            # Hard limit: stop at max_items
            elif len(selected) < self.max_items:
                if total_tokens + tokens <= max_tokens:
                    selected.append(item)
                    total_tokens += tokens
            else:
                break

        return selected

    def allocate_context(
        self,
        max_tokens: int,
        shared_memory_ratio: float = 0.6,
        artifacts_ratio: float = 0.3,
        system_ratio: float = 0.1
    ) -> dict[str, int]:
        """
        Allocate context window budget across sources.

        Args:
            max_tokens: Total available tokens
            shared_memory_ratio: Fraction for shared memory (default 60%)
            artifacts_ratio: Fraction for session artifacts (default 30%)
            system_ratio: Fraction for system prompt (default 10%)

        Returns:
            Dict mapping source name to token budget
        """
        return {
            "shared_memory": int(max_tokens * shared_memory_ratio),
            "artifacts": int(max_tokens * artifacts_ratio),
            "system": int(max_tokens * system_ratio)
        }
