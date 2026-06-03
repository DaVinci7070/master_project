import logging
from datetime import datetime, timezone
from typing import Optional

from app.models.sql.improvement_models import ImprovementAttempt
from app.repositories.improvement_repository import ImprovementRepository
from app.core.versioning import VersionService

log = logging.getLogger(__name__)


class RollbackService:
    """
    Orchestrates granular rollbacks for failed improvements.

    Uses VersionService for the actual version restore and ImprovementRepository
    to update the attempt status. Designed for fast rollback (<5 minutes target).

    Example:
        async with get_session() as session:
            version_service = VersionService(session)
            improvement_repo = ImprovementRepository(session)
            rollback_service = RollbackService(version_service, improvement_repo)

            success = await rollback_service.rollback_improvement(
                attempt=attempt,
                reason="degradation"
            )
    """

    def __init__(
        self,
        version_service: VersionService,
        improvement_repo: ImprovementRepository,
    ):
        """
        Initialize the rollback service.

        Args:
            version_service: VersionService for version operations.
            improvement_repo: ImprovementRepository for status updates.
        """
        self.version_service = version_service
        self.improvement_repo = improvement_repo

    async def rollback_improvement(
        self,
        attempt: ImprovementAttempt,
        reason: str,
    ) -> bool:
        """
        Rollback a single improvement to its previous version.

        Args:
            attempt: The improvement attempt to rollback.
            reason: Why rollback is happening (degradation, failed_ab, manual).

        Returns:
            True if rollback succeeded, False otherwise.
        """
        start_time = datetime.now(timezone.utc)
        log.info(
            f"Starting rollback for attempt={attempt.id}, "
            f"artifact={attempt.artifact_type}/{attempt.artifact_id[:8]}..., "
            f"reason={reason}"
        )

        if attempt.version_before is None:
            log.error(
                f"Cannot rollback attempt={attempt.id}: "
                "version_before is not set (no baseline)"
            )
            return False

        try:
            rolled_back = await self.version_service.rollback(
                artifact_type=attempt.artifact_type,
                artifact_id=attempt.artifact_id,
                version_index=attempt.version_before,
            )

            if rolled_back is None:
                log.error(
                    f"Rollback failed for attempt={attempt.id}: "
                    "VersionService.rollback returned None"
                )
                return False

            await self.improvement_repo.update_status(
                attempt_id=str(attempt.id),
                status="rolled_back",
                failure_reason=f"Rolled back due to: {reason}",
            )

            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()

            log.info(
                f"Rollback complete for attempt={attempt.id}: "
                f"reverted to version {attempt.version_before}, "
                f"duration={duration:.2f}s"
            )

            if duration > 240:
                log.warning(
                    f"Rollback took {duration:.2f}s, approaching 5-minute target"
                )

            return True

        except Exception as e:
            log.error(
                f"Rollback failed for attempt={attempt.id}: {e}",
                exc_info=True
            )
            return False

    async def rollback_by_improvement_id(
        self,
        improvement_id: str,
        reason: str,
    ) -> bool:
        """
        Convenience method to rollback by improvement ID.

        Args:
            improvement_id: UUID of the improvement attempt.
            reason: Why rollback is happening.

        Returns:
            True if rollback succeeded, False otherwise.
        """
        log.info(f"Looking up improvement attempt={improvement_id}")

        attempt = await self.improvement_repo.get_by_id(improvement_id)
        if attempt is None:
            log.error(f"Improvement attempt not found: {improvement_id}")
            return False

        return await self.rollback_improvement(attempt, reason)

    async def get_rollback_info(
        self,
        attempt: ImprovementAttempt,
    ) -> Optional[dict]:
        """
        Get version comparison for potential rollback preview.

        Shows what would change if rollback is executed. Useful for
        manual review before triggering rollback.

        Args:
            attempt: The improvement attempt to preview rollback for.

        Returns:
            Dict with version comparison info, or None if comparison fails.
        """
        if attempt.version_before is None:
            log.warning(
                f"Cannot preview rollback for attempt={attempt.id}: "
                "version_before is not set"
            )
            return None

        if attempt.version_after is None:
            log.warning(
                f"Cannot preview rollback for attempt={attempt.id}: "
                "version_after is not set (improvement not applied)"
            )
            return None

        try:
            comparison = await self.version_service.compare_versions(
                artifact_type=attempt.artifact_type,
                artifact_id=attempt.artifact_id,
                version_a=attempt.version_after,
                version_b=attempt.version_before,
            )

            return {
                "attempt_id": str(attempt.id),
                "artifact_type": attempt.artifact_type,
                "artifact_id": attempt.artifact_id,
                "current_version": attempt.version_after,
                "target_version": attempt.version_before,
                "changed_fields": comparison["changed_fields"],
                "changes": comparison["changes"],
            }

        except ValueError as e:
            log.error(
                f"Failed to compare versions for attempt={attempt.id}: {e}"
            )
            return None
