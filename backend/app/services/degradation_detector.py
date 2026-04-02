"""
Degradation detector for metric monitoring with hysteresis.

This service detects sustained metric degradation after improvements
are applied. Uses hysteresis to prevent false positive rollbacks from
momentary spikes - requires multiple consecutive degraded checks.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger(__name__)


class DegradationDetector:
    """
    Detects metric degradation with hysteresis to prevent false positives.

    Hysteresis: Requires sustained degradation over multiple consecutive checks
    before triggering rollback, not just a momentary spike. This prevents
    rollbacks due to temporary traffic spikes, cold starts, or measurement noise.

    Configuration:
        threshold_percent: How much degradation is acceptable (default 10%)
        window_seconds: Time window for considering samples (default 5 min)
        min_samples: Minimum samples needed for valid measurement (default 10)
        sustained_count: Consecutive degraded checks before triggering (default 3)

    Example:
        detector = DegradationDetector(
            threshold_percent=0.10,  # 10% degradation threshold
            sustained_count=3        # Require 3 consecutive degraded checks
        )

        degradation = await detector.check_degradation(
            improvement_id="uuid",
            baseline_mean=100.0,
            current_samples=[88.0, 87.5, 89.0, 85.0, ...]
        )

        if degradation:
            # Trigger rollback
            await rollback_service.rollback_improvement(attempt, degradation)
    """

    def __init__(
        self,
        threshold_percent: float = 0.10,  # 10% degradation
        window_seconds: int = 300,  # 5 minutes
        min_samples: int = 10,
        sustained_count: int = 3,  # Require 3 consecutive degraded checks
    ):
        """
        Initialize the degradation detector.

        Args:
            threshold_percent: Degradation threshold as decimal (0.10 = 10%).
            window_seconds: Time window for samples (default 300 = 5 min).
            min_samples: Minimum samples required for valid check.
            sustained_count: Consecutive degraded checks to trigger rollback.
        """
        self.threshold = threshold_percent
        self.window = timedelta(seconds=window_seconds)
        self.min_samples = min_samples
        self.sustained_count = sustained_count

        # Internal tracking state
        self._degradation_counts: dict[str, int] = {}  # improvement_id -> consecutive count
        self._last_check: dict[str, datetime] = {}  # improvement_id -> last check time

        log.info(
            f"DegradationDetector initialized: "
            f"threshold={threshold_percent:.1%}, "
            f"min_samples={min_samples}, "
            f"sustained_count={sustained_count}"
        )

    async def check_degradation(
        self,
        improvement_id: str,
        baseline_mean: float,
        current_samples: list[float],
    ) -> Optional[str]:
        """
        Check if metrics have degraded beyond threshold.

        Compares current sample mean against baseline. If degradation exceeds
        threshold, increments the consecutive counter. Only returns a degradation
        reason after sustained_count consecutive degraded checks.

        Args:
            improvement_id: UUID of the improvement being monitored.
            baseline_mean: Mean metric value before improvement.
            current_samples: Recent metric samples after improvement.

        Returns:
            Degradation reason string if sustained degradation detected,
            None otherwise (including if not enough data).
        """
        # Not enough data for valid measurement
        if len(current_samples) < self.min_samples:
            log.debug(
                f"Improvement {improvement_id[:8]}...: "
                f"insufficient samples ({len(current_samples)}/{self.min_samples})"
            )
            return None

        # Handle edge case: zero baseline
        if baseline_mean == 0:
            log.warning(
                f"Improvement {improvement_id[:8]}...: "
                "baseline_mean is zero, cannot calculate degradation"
            )
            return None

        # Calculate current mean and degradation
        current_mean = sum(current_samples) / len(current_samples)
        degradation = (current_mean - baseline_mean) / baseline_mean

        # Update last check time
        self._last_check[improvement_id] = datetime.now()

        # Check if degraded beyond threshold
        # Note: negative degradation means current is lower than baseline
        # For metrics where higher is better (quality), negative is bad
        # For metrics where lower is better (latency, error_rate), positive is bad
        # This detector assumes higher-is-better metrics
        if degradation < -self.threshold:
            # Increment consecutive counter
            self._degradation_counts[improvement_id] = (
                self._degradation_counts.get(improvement_id, 0) + 1
            )
            count = self._degradation_counts[improvement_id]

            log.info(
                f"Improvement {improvement_id[:8]}...: degradation detected "
                f"({degradation:.1%}), consecutive count={count}/{self.sustained_count}"
            )

            # Check if sustained threshold reached
            if count >= self.sustained_count:
                reason = (
                    f"Sustained degradation: {abs(degradation):.1%} drop "
                    f"(baseline={baseline_mean:.2f}, current={current_mean:.2f}) "
                    f"over {count} consecutive checks"
                )
                log.warning(
                    f"Improvement {improvement_id[:8]}...: "
                    f"sustained degradation threshold reached - {reason}"
                )
                return reason
        else:
            # Reset counter if not degraded
            if improvement_id in self._degradation_counts:
                log.debug(
                    f"Improvement {improvement_id[:8]}...: "
                    f"metrics recovered, resetting counter "
                    f"(was {self._degradation_counts[improvement_id]})"
                )
            self._degradation_counts[improvement_id] = 0

        return None

    def reset_tracking(self, improvement_id: str) -> None:
        """
        Reset degradation tracking for an improvement.

        Call after rollback to clear state for the improvement.

        Args:
            improvement_id: UUID of the improvement to reset.
        """
        was_tracked = improvement_id in self._degradation_counts

        self._degradation_counts.pop(improvement_id, None)
        self._last_check.pop(improvement_id, None)

        if was_tracked:
            log.info(f"Reset tracking for improvement {improvement_id[:8]}...")

    def get_status(self, improvement_id: str) -> dict:
        """
        Get current tracking status for monitoring.

        Useful for dashboards and debugging to see current state.

        Args:
            improvement_id: UUID of the improvement to check.

        Returns:
            Dict with consecutive_checks, threshold, sustained_required,
            and last_check timestamp.
        """
        return {
            "consecutive_checks": self._degradation_counts.get(improvement_id, 0),
            "threshold": self.threshold,
            "sustained_required": self.sustained_count,
            "min_samples": self.min_samples,
            "last_check": self._last_check.get(improvement_id),
        }

    def get_all_tracked(self) -> dict[str, dict]:
        """
        Get status for all currently tracked improvements.

        Returns:
            Dict mapping improvement_id to status dict.
        """
        all_ids = set(self._degradation_counts.keys()) | set(self._last_check.keys())
        return {imp_id: self.get_status(imp_id) for imp_id in all_ids}
