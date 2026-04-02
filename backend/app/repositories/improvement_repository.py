"""
Improvement repository for improvement attempt data access.

This module implements CRUD operations and 3-strike rule queries for
ImprovementAttempt records. The repository enables tracking how many
times the system has attempted to fix a specific finding.
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sql.improvement_models import ImprovementAttempt
from app.models.schemas.control_schemas import ImprovementAttemptCreate

log = logging.getLogger(__name__)


class ImprovementRepository:
    """
    Repository for ImprovementAttempt database operations.

    Provides methods for:
    - Creating and tracking improvement attempts
    - 3-strike rule enforcement (checking attempt counts per fingerprint)
    - Status updates and completion tracking

    All operations are async for non-blocking database access.
    """

    def __init__(self, session: AsyncSession):
        """
        Initialize repository with database session.

        Args:
            session: SQLAlchemy async session for database operations.
        """
        self.session = session

    async def create(self, data: ImprovementAttemptCreate) -> ImprovementAttempt:
        """
        Create a new improvement attempt.

        Args:
            data: Validated improvement attempt data from schema.

        Returns:
            Created ImprovementAttempt database model.
        """
        log.info(
            f"Creating improvement attempt for fingerprint={data.finding_fingerprint[:8]}..., "
            f"artifact_type={data.artifact_type}, attempt={data.attempt_number}"
        )

        db_attempt = ImprovementAttempt(
            finding_fingerprint=data.finding_fingerprint,
            attempt_number=data.attempt_number,
            artifact_type=data.artifact_type,
            artifact_id=data.artifact_id,
            version_before=data.version_before,
            ab_test_id=data.ab_test_id,
        )

        self.session.add(db_attempt)
        await self.session.commit()
        await self.session.refresh(db_attempt)

        log.info(f"Created improvement attempt id={db_attempt.id}")
        return db_attempt

    async def get_by_id(self, attempt_id: str) -> Optional[ImprovementAttempt]:
        """
        Get an improvement attempt by its ID.

        Args:
            attempt_id: UUID of the improvement attempt.

        Returns:
            ImprovementAttempt or None if not found.
        """
        stmt = select(ImprovementAttempt).where(ImprovementAttempt.id == attempt_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_fingerprint(
        self, fingerprint: str, limit: int = 10
    ) -> List[ImprovementAttempt]:
        """
        Get all improvement attempts for a specific finding fingerprint.

        Results are ordered by attempt_number ascending.

        Args:
            fingerprint: Finding fingerprint hash.
            limit: Maximum number of attempts to return.

        Returns:
            List of ImprovementAttempt records.
        """
        stmt = (
            select(ImprovementAttempt)
            .where(ImprovementAttempt.finding_fingerprint == fingerprint)
            .order_by(ImprovementAttempt.attempt_number.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_attempt_count(self, fingerprint: str) -> int:
        """
        Count all improvement attempts for a specific fingerprint.

        Used for 3-strike rule enforcement.

        Args:
            fingerprint: Finding fingerprint hash.

        Returns:
            Number of attempts for this fingerprint.
        """
        stmt = (
            select(func.count())
            .select_from(ImprovementAttempt)
            .where(ImprovementAttempt.finding_fingerprint == fingerprint)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def should_skip_finding(
        self, fingerprint: str, max_attempts: int = 3
    ) -> bool:
        """
        Check if a finding should be skipped due to 3-strike rule.

        Returns True if the finding has already exhausted its allowed
        improvement attempts.

        Args:
            fingerprint: Finding fingerprint hash.
            max_attempts: Maximum allowed attempts (default 3).

        Returns:
            True if count >= max_attempts (should skip), False otherwise.
        """
        count = await self.get_attempt_count(fingerprint)
        should_skip = count >= max_attempts

        if should_skip:
            log.info(
                f"Finding fingerprint={fingerprint[:8]}... exhausted "
                f"{count}/{max_attempts} attempts, should skip"
            )

        return should_skip

    async def get_active_attempts(self) -> List[ImprovementAttempt]:
        """
        Get all currently active improvement attempts.

        Active attempts are those with status 'pending' or 'testing'.

        Returns:
            List of active ImprovementAttempt records.
        """
        stmt = (
            select(ImprovementAttempt)
            .where(ImprovementAttempt.status.in_(["pending", "testing"]))
            .order_by(ImprovementAttempt.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_status(
        self,
        attempt_id: str,
        status: str,
        failure_reason: Optional[str] = None,
        version_after: Optional[int] = None,
    ) -> Optional[ImprovementAttempt]:
        """
        Update the status of an improvement attempt.

        Args:
            attempt_id: UUID of the attempt to update.
            status: New status value.
            failure_reason: Optional reason if status is 'failed'.
            version_after: Optional version after improvement applied.

        Returns:
            Updated ImprovementAttempt or None if not found.
        """
        log.info(f"Updating status for attempt={attempt_id}, status={status}")

        attempt = await self.get_by_id(attempt_id)
        if not attempt:
            log.warning(f"Improvement attempt not found: {attempt_id}")
            return None

        attempt.status = status
        if failure_reason is not None:
            attempt.failure_reason = failure_reason
        if version_after is not None:
            attempt.version_after = version_after

        await self.session.commit()
        await self.session.refresh(attempt)

        log.info(f"Updated attempt status: id={attempt_id}, status={status}")
        return attempt

    async def mark_completed(
        self,
        attempt_id: str,
        success: bool,
        failure_reason: Optional[str] = None,
    ) -> Optional[ImprovementAttempt]:
        """
        Mark an improvement attempt as completed.

        Sets the status to 'success' or 'failed' and records completion time.

        Args:
            attempt_id: UUID of the attempt to complete.
            success: True for success, False for failure.
            failure_reason: Optional reason if success is False.

        Returns:
            Updated ImprovementAttempt or None if not found.
        """
        status = "success" if success else "failed"
        log.info(
            f"Marking attempt={attempt_id} as completed, success={success}"
        )

        attempt = await self.get_by_id(attempt_id)
        if not attempt:
            log.warning(f"Improvement attempt not found: {attempt_id}")
            return None

        attempt.status = status
        attempt.completed_at = datetime.now(timezone.utc)
        if failure_reason is not None:
            attempt.failure_reason = failure_reason

        await self.session.commit()
        await self.session.refresh(attempt)

        log.info(
            f"Completed attempt: id={attempt_id}, status={status}, "
            f"completed_at={attempt.completed_at}"
        )
        return attempt
