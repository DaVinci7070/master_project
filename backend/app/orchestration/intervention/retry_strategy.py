import asyncio
import logging
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)


ApproachType = Literal["direct", "simplified", "alternative", "minimal", "fallback"]


@dataclass(frozen=True)
class ApproachConfig:
    """Configuration for a build approach."""
    name: ApproachType
    constraints: list[str]
    description: str


class ApproachSelector:
    """
    Selects building approach based on attempt number.

    Per CONTEXT: How to vary approaches across retry attempts.

    Attempt progression:
    1. direct: Full implementation with standard library
    2. simplified: Reduce complexity, focus on core functionality
    3. alternative: Try different library or pattern
    4. minimal: Absolute minimum functionality
    5. fallback: Workaround or graceful degradation
    """

    APPROACHES: dict[int, ApproachConfig] = {
        1: ApproachConfig(
            name="direct",
            constraints=[
                "Use standard library where possible",
                "Full feature implementation",
                "Include comprehensive error handling"
            ],
            description="Direct implementation with standard patterns"
        ),
        2: ApproachConfig(
            name="simplified",
            constraints=[
                "Reduce complexity - minimal viable functionality",
                "Fewer edge cases, focus on core use case",
                "Simplify error handling to basic try/except"
            ],
            description="Simplified version focusing on core functionality"
        ),
        3: ApproachConfig(
            name="alternative",
            constraints=[
                "Try different library or pattern than previous attempts",
                "Research alternative solutions",
                "Consider different algorithmic approach"
            ],
            description="Alternative approach using different techniques"
        ),
        4: ApproachConfig(
            name="minimal",
            constraints=[
                "Absolute minimum functionality",
                "Single happy path only",
                "No edge case handling",
                "Hardcode reasonable defaults if needed"
            ],
            description="Minimal viable implementation"
        ),
        5: ApproachConfig(
            name="fallback",
            constraints=[
                "Implement workaround or mock if necessary",
                "Graceful degradation acceptable",
                "Return sensible defaults on error",
                "Log extensively for debugging"
            ],
            description="Fallback with graceful degradation"
        ),
    }

    @classmethod
    def select(cls, attempt_number: int) -> ApproachConfig:
        """
        Select approach for given attempt number.

        Args:
            attempt_number: Current attempt (1-5)

        Returns:
            ApproachConfig for this attempt
        """
        attempt = max(1, min(attempt_number, 5))
        return cls.APPROACHES[attempt]

    @classmethod
    def get_constraints_for_attempt(cls, attempt_number: int) -> list[str]:
        """Get constraints list for a specific attempt."""
        config = cls.select(attempt_number)
        return config.constraints

    @classmethod
    def build_context_with_failures(
        cls,
        attempt_number: int,
        previous_failures: list[str]
    ) -> str:
        """
        Build context string including approach and previous failures.

        Per CONTEXT: Include previous failed attempts so Developer Team
        tries different approaches.
        """
        config = cls.select(attempt_number)

        lines = [
            f"## Build Approach: {config.name.upper()}",
            f"**Description:** {config.description}",
            "",
            "**Constraints:**"
        ]

        for constraint in config.constraints:
            lines.append(f"- {constraint}")

        if previous_failures:
            lines.extend([
                "",
                "## Previous Failed Attempts (try different approach)",
            ])
            for i, failure in enumerate(previous_failures, 1):
                lines.append(f"{i}. {failure}")

        return "\n".join(lines)


class RetryStrategy:
    """
    Retry strategy with exponential backoff for intervention.

    Per CONTEXT: 5 attempts before notifying user.
    Per RESEARCH: Progressive backoff with increasing delays.
    """

    RETRY_DELAYS: dict[int, int] = {
        1: 30,
        2: 60,
        3: 120,
        4: 300,
    }

    MAX_ATTEMPTS = 5

    @classmethod
    def should_retry(cls, attempt_number: int) -> bool:
        """Check if more retry attempts are available."""
        return attempt_number < cls.MAX_ATTEMPTS

    @classmethod
    def get_retry_delay(cls, attempt_number: int) -> int:
        """
        Get delay before next retry attempt.

        Per CONTEXT: Claude's discretion on timeout between attempts.
        Progressive backoff: later attempts wait longer.

        Args:
            attempt_number: Just-completed attempt number

        Returns:
            Seconds to wait before next attempt
        """
        return cls.RETRY_DELAYS.get(attempt_number, 60)

    @classmethod
    async def wait_before_retry(cls, attempt_number: int) -> None:
        """
        Wait appropriate time before retry.

        Args:
            attempt_number: Just-completed attempt number
        """
        delay = cls.get_retry_delay(attempt_number)
        logger.info(
            f"Waiting {delay}s before retry attempt {attempt_number + 1}"
        )
        await asyncio.sleep(delay)

    @classmethod
    def get_approach_for_attempt(cls, attempt_number: int) -> ApproachConfig:
        """Get the approach configuration for an attempt."""
        return ApproachSelector.select(attempt_number)

    @classmethod
    def format_user_notification(
        cls,
        challenge_id: str,
        attempt_number: int,
        success: bool,
        message: str,
        built_capabilities: list[str]
    ) -> dict:
        """
        Format user notification for intervention result.

        Per CONTEXT: Always notify user when challenge finally executes.
        """
        if success:
            return {
                "type": "challenge_resolved",
                "challenge_id": challenge_id,
                "attempts_taken": attempt_number,
                "capabilities_built": len(built_capabilities),
                "capability_ids": built_capabilities,
                "message": (
                    f"Challenge resolved after {attempt_number} attempt(s). "
                    f"Built {len(built_capabilities)} new capabilities."
                ),
                "success": True
            }
        else:
            return {
                "type": "challenge_failed",
                "challenge_id": challenge_id,
                "attempts_taken": attempt_number,
                "max_attempts": cls.MAX_ATTEMPTS,
                "message": message,
                "next_steps": [
                    "Review failure reasons in dashboard",
                    "Check if challenge requires external resources",
                    "Consider simplifying challenge or adding capability manually"
                ],
                "success": False
            }
