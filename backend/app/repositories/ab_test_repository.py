import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sql.ab_test_models import ABTest, ABTestSample
from app.models.schemas.ab_test_schemas import ABTestCreate, ABTestSampleCreate

log = logging.getLogger(__name__)


class ABTestRepository:
    """
    Repository for ABTest and ABTestSample database operations.

    Provides methods for:
    - Creating and tracking A/B tests
    - Recording and retrieving samples by variant
    - Test queue management (one test per artifact)
    - Sample count tracking and minimum sample checks

    All operations are async for non-blocking database access.
    """

    def __init__(self, session: AsyncSession):
        """
        Initialize repository with database session.

        Args:
            session: SQLAlchemy async session for database operations.
        """
        self.session = session

    async def create_test(self, data: ABTestCreate) -> ABTest:
        """
        Create a new A/B test.

        Args:
            data: Validated A/B test data from schema.

        Returns:
            Created ABTest database model with status="pending".
        """
        log.info(
            f"Creating A/B test for improvement_attempt_id={data.improvement_attempt_id}, "
            f"artifact_type={data.artifact_type}, artifact_id={data.artifact_id[:8]}..."
        )

        db_test = ABTest(
            improvement_attempt_id=data.improvement_attempt_id,
            artifact_type=data.artifact_type,
            artifact_id=data.artifact_id,
            version_baseline=data.version_baseline,
            version_improvement=data.version_improvement,
            metric_weights=data.metric_weights,
            status="pending",
            samples_baseline=0,
            samples_improvement=0,
        )

        self.session.add(db_test)
        await self.session.commit()
        await self.session.refresh(db_test)

        log.info(f"Created A/B test id={db_test.id}")
        return db_test

    async def get_test(self, test_id: str) -> Optional[ABTest]:
        """
        Get an A/B test by its ID.

        Args:
            test_id: UUID of the A/B test.

        Returns:
            ABTest or None if not found.
        """
        stmt = select(ABTest).where(ABTest.id == test_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_test_by_improvement(
        self, improvement_attempt_id: str
    ) -> Optional[ABTest]:
        """
        Find A/B test linked to an improvement attempt.

        Args:
            improvement_attempt_id: UUID of the ImprovementAttempt.

        Returns:
            ABTest or None if not found.
        """
        stmt = select(ABTest).where(
            ABTest.improvement_attempt_id == improvement_attempt_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_test_status(
        self, test_id: str, status: str, **kwargs
    ) -> Optional[ABTest]:
        """
        Update the status of an A/B test and optional fields.

        Sets completed_at timestamp if status is "completed" or "cancelled".
        Supports updating p_value, effect_size, is_significant, confidence intervals.

        Args:
            test_id: UUID of the test to update.
            status: New status value.
            **kwargs: Optional fields to update (p_value, effect_size, etc.).

        Returns:
            Updated ABTest or None if not found.
        """
        log.info(f"Updating status for test={test_id}, status={status}")

        test = await self.get_test(test_id)
        if not test:
            log.warning(f"A/B test not found: {test_id}")
            return None

        test.status = status

        if status in ("completed", "cancelled"):
            test.completed_at = datetime.now(timezone.utc)

        for key, value in kwargs.items():
            if hasattr(test, key) and value is not None:
                setattr(test, key, value)

        await self.session.commit()
        await self.session.refresh(test)

        log.info(f"Updated test status: id={test_id}, status={status}")
        return test

    async def add_sample(self, data: ABTestSampleCreate) -> ABTestSample:
        """
        Create a sample record and update parent test's sample count.

        Args:
            data: Validated sample data from schema.

        Returns:
            Created ABTestSample database model.
        """
        log.info(
            f"Adding sample to test={data.test_id[:8]}..., "
            f"variant={data.variant}, composite_score={data.composite_score:.3f}"
        )

        db_sample = ABTestSample(
            test_id=data.test_id,
            execution_id=data.execution_id,
            variant=data.variant,
            quality_score=data.quality_score,
            latency_ms=data.latency_ms,
            is_error=1 if data.is_error else 0,
            composite_score=data.composite_score,
        )

        self.session.add(db_sample)

        test = await self.get_test(data.test_id)
        if test:
            if data.variant == "baseline":
                test.samples_baseline += 1
            elif data.variant == "improvement":
                test.samples_improvement += 1

        await self.session.commit()
        await self.session.refresh(db_sample)

        log.info(
            f"Added sample id={db_sample.id}, "
            f"test now has {test.samples_baseline}/{test.samples_improvement} samples"
        )
        return db_sample

    async def get_samples(
        self, test_id: str, variant: Optional[str] = None
    ) -> List[ABTestSample]:
        """
        Get all samples for an A/B test.

        Args:
            test_id: UUID of the A/B test.
            variant: Optional filter by "baseline" or "improvement".

        Returns:
            List of ABTestSample records ordered by created_at.
        """
        stmt = select(ABTestSample).where(ABTestSample.test_id == test_id)

        if variant:
            stmt = stmt.where(ABTestSample.variant == variant)

        stmt = stmt.order_by(ABTestSample.created_at.asc())

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_sample_counts(self, test_id: str) -> dict[str, int]:
        """
        Get sample counts for both variants.

        Args:
            test_id: UUID of the A/B test.

        Returns:
            Dictionary with "baseline" and "improvement" counts.
        """
        test = await self.get_test(test_id)
        if not test:
            log.warning(f"A/B test not found: {test_id}")
            return {"baseline": 0, "improvement": 0}

        return {
            "baseline": test.samples_baseline,
            "improvement": test.samples_improvement,
        }

    async def get_active_test_for_artifact(
        self, artifact_type: str, artifact_id: str
    ) -> Optional[ABTest]:
        """
        Find active test for a specific artifact.

        Used to check if new test can start (one test per artifact constraint).

        Args:
            artifact_type: Type of artifact (prompt, agent, skill).
            artifact_id: UUID of the artifact.

        Returns:
            ABTest with status in ("pending", "running") or None if no active test.
        """
        stmt = select(ABTest).where(
            and_(
                ABTest.artifact_type == artifact_type,
                ABTest.artifact_id == artifact_id,
                ABTest.status.in_(["pending", "running"]),
            )
        )
        result = await self.session.execute(stmt)
        active_test = result.scalar_one_or_none()

        if active_test:
            log.info(
                f"Found active test id={active_test.id} for "
                f"artifact={artifact_type}:{artifact_id[:8]}..."
            )

        return active_test

    async def get_active_tests(self) -> List[ABTest]:
        """
        Get all active tests.

        Returns:
            List of ABTest records with status in ("pending", "running"),
            ordered by created_at descending.
        """
        stmt = (
            select(ABTest)
            .where(ABTest.status.in_(["pending", "running"]))
            .order_by(ABTest.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def queue_improvement(
        self, artifact_type: str, artifact_id: str, improvement_attempt_id: str
    ) -> None:
        """
        Queue an improvement attempt for testing when test already running.

        Adds improvement_attempt_id to the active test's queued_ids list.

        Args:
            artifact_type: Type of artifact (prompt, agent, skill).
            artifact_id: UUID of the artifact.
            improvement_attempt_id: UUID of ImprovementAttempt to queue.
        """
        active_test = await self.get_active_test_for_artifact(
            artifact_type, artifact_id
        )

        if not active_test:
            log.warning(
                f"No active test found for artifact={artifact_type}:{artifact_id[:8]}..., "
                f"cannot queue improvement_attempt_id={improvement_attempt_id}"
            )
            return

        if active_test.queued_ids is None:
            active_test.queued_ids = []

        active_test.queued_ids.append(improvement_attempt_id)

        await self.session.commit()
        await self.session.refresh(active_test)

        log.info(
            f"Queued improvement_attempt_id={improvement_attempt_id} "
            f"for test={active_test.id}, queue size={len(active_test.queued_ids)}"
        )

    async def pop_queued_improvement(
        self, artifact_type: str, artifact_id: str
    ) -> Optional[str]:
        """
        Get and remove the next queued improvement_attempt_id.

        Args:
            artifact_type: Type of artifact (prompt, agent, skill).
            artifact_id: UUID of the artifact.

        Returns:
            UUID of next queued improvement_attempt_id or None if queue is empty.
        """
        stmt = (
            select(ABTest)
            .where(
                and_(
                    ABTest.artifact_type == artifact_type,
                    ABTest.artifact_id == artifact_id,
                    ABTest.status.in_(["completed", "cancelled"]),
                )
            )
            .order_by(ABTest.completed_at.desc())
        )
        result = await self.session.execute(stmt)
        test = result.scalar_one_or_none()

        if not test or not test.queued_ids or len(test.queued_ids) == 0:
            log.info(
                f"No queued improvements for artifact={artifact_type}:{artifact_id[:8]}..."
            )
            return None

        next_id = test.queued_ids.pop(0)

        await self.session.commit()
        await self.session.refresh(test)

        log.info(
            f"Popped improvement_attempt_id={next_id} from test={test.id}, "
            f"queue size={len(test.queued_ids)}"
        )
        return next_id

    async def has_minimum_samples(
        self, test_id: str, min_per_variant: int = 5
    ) -> bool:
        """
        Check if test has minimum samples for both variants.

        Args:
            test_id: UUID of the A/B test.
            min_per_variant: Minimum samples required per variant (default 5).

        Returns:
            True if both variants have at least min_per_variant samples.
        """
        test = await self.get_test(test_id)
        if not test:
            log.warning(f"A/B test not found: {test_id}")
            return False

        has_minimum = (
            test.samples_baseline >= min_per_variant
            and test.samples_improvement >= min_per_variant
        )

        log.info(
            f"Test {test_id[:8]}... has "
            f"{test.samples_baseline}/{test.samples_improvement} samples, "
            f"minimum required: {min_per_variant}, has_minimum={has_minimum}"
        )

        return has_minimum
