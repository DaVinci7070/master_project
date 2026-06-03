import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update

from app.models.sql.intervention_models import BlockedChallenge, ChallengeStatus
from app.models.schemas.analysis_schemas import CapabilityAssessment

logger = logging.getLogger(__name__)


class BlockedChallengeQueue:
    """
    Async queue manager for blocked challenges.

    Per CONTEXT decisions:
    - Challenge stored in database queue (survives restarts)
    - Tracks retry attempts and failure reasons
    - 5 attempts max before failing

    Per RESEARCH pitfall 6:
    - Use SELECT FOR UPDATE to prevent concurrent processing collisions
    """

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def enqueue(
        self,
        execution_id: str,
        project_id: str,
        challenge_text: str,
        assessment: CapabilityAssessment
    ) -> BlockedChallenge:
        """
        Enqueue a blocked challenge for intervention.

        Per CONTEXT: Challenge stored in database queue (survives restarts).

        Args:
            execution_id: Correlation ID for this execution
            project_id: Project ID for context
            challenge_text: The challenge that is blocked
            assessment: Full capability assessment from Phase 9

        Returns:
            Created BlockedChallenge record
        """
        challenge = BlockedChallenge(
            id=str(uuid.uuid4()),
            execution_id=execution_id,
            project_id=project_id,
            challenge_text=challenge_text,
            assessment_result=assessment.model_dump(),
            gaps_snapshot=[gap.model_dump() for gap in assessment.gaps],
            status=ChallengeStatus.QUEUED
        )

        async with self.session_factory() as db:
            db.add(challenge)
            await db.commit()
            await db.refresh(challenge)

        logger.info(
            f"Queued blocked challenge: id={challenge.id[:8]}..., "
            f"execution_id={execution_id[:8]}..., gaps={len(assessment.gaps)}"
        )

        return challenge

    async def get_next_queued(self) -> Optional[BlockedChallenge]:
        """
        Get next challenge in QUEUED status for processing.

        Per RESEARCH pitfall 6: Use FOR UPDATE to prevent concurrent collisions.
        Returns oldest queued challenge (FIFO order).
        """
        async with self.session_factory() as db:
            result = await db.execute(
                select(BlockedChallenge)
                .where(BlockedChallenge.status == ChallengeStatus.QUEUED.value)
                .order_by(BlockedChallenge.created_at.asc())
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def get_by_id(self, challenge_id: str) -> Optional[BlockedChallenge]:
        """Get challenge by ID."""
        async with self.session_factory() as db:
            result = await db.execute(
                select(BlockedChallenge).where(BlockedChallenge.id == challenge_id)
            )
            return result.scalar_one_or_none()

    async def mark_building(self, challenge_id: str) -> None:
        """Mark challenge as actively being built."""
        async with self.session_factory() as db:
            await db.execute(
                update(BlockedChallenge)
                .where(BlockedChallenge.id == challenge_id)
                .values(
                    status=ChallengeStatus.BUILDING.value,
                    updated_at=datetime.now(timezone.utc)
                )
            )
            await db.commit()
        logger.debug(f"Challenge {challenge_id[:8]}... marked BUILDING")

    async def mark_built(
        self,
        challenge_id: str,
        built_capability_ids: list[str]
    ) -> None:
        """Mark challenge as having capabilities built."""
        async with self.session_factory() as db:
            await db.execute(
                update(BlockedChallenge)
                .where(BlockedChallenge.id == challenge_id)
                .values(
                    status=ChallengeStatus.BUILT.value,
                    built_capability_ids=built_capability_ids,
                    updated_at=datetime.now(timezone.utc)
                )
            )
            await db.commit()
        logger.debug(f"Challenge {challenge_id[:8]}... marked BUILT with {len(built_capability_ids)} capabilities")

    async def mark_injected(self, challenge_id: str) -> None:
        """Mark challenge as having capabilities injected."""
        async with self.session_factory() as db:
            await db.execute(
                update(BlockedChallenge)
                .where(BlockedChallenge.id == challenge_id)
                .values(
                    status=ChallengeStatus.INJECTED.value,
                    updated_at=datetime.now(timezone.utc)
                )
            )
            await db.commit()
        logger.debug(f"Challenge {challenge_id[:8]}... marked INJECTED")

    async def mark_resolved(self, challenge_id: str) -> None:
        """Mark challenge as resolved (successfully executed after intervention)."""
        async with self.session_factory() as db:
            await db.execute(
                update(BlockedChallenge)
                .where(BlockedChallenge.id == challenge_id)
                .values(
                    status=ChallengeStatus.RESOLVED.value,
                    resolved_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
            )
            await db.commit()
        logger.info(f"Challenge {challenge_id[:8]}... RESOLVED")

    async def increment_attempt(
        self,
        challenge_id: str,
        failure_reason: str
    ) -> bool:
        """
        Increment attempt counter after failure.

        Per CONTEXT: 5 attempts before notifying user.

        Returns:
            True if more attempts remain, False if max attempts reached.
        """
        async with self.session_factory() as db:
            result = await db.execute(
                select(BlockedChallenge).where(BlockedChallenge.id == challenge_id)
            )
            challenge = result.scalar_one()

            failure_reasons = list(challenge.failure_reasons or [])
            failure_reasons.append(failure_reason)

            new_attempt = challenge.attempt_number + 1

            if new_attempt > challenge.max_attempts:
                await db.execute(
                    update(BlockedChallenge)
                    .where(BlockedChallenge.id == challenge_id)
                    .values(
                        status=ChallengeStatus.FAILED.value,
                        attempt_number=new_attempt,
                        failure_reasons=failure_reasons,
                        updated_at=datetime.now(timezone.utc)
                    )
                )
                await db.commit()
                logger.warning(
                    f"Challenge {challenge_id[:8]}... FAILED after {challenge.max_attempts} attempts"
                )
                return False

            await db.execute(
                update(BlockedChallenge)
                .where(BlockedChallenge.id == challenge_id)
                .values(
                    status=ChallengeStatus.QUEUED.value,
                    attempt_number=new_attempt,
                    failure_reasons=failure_reasons,
                    updated_at=datetime.now(timezone.utc)
                )
            )
            await db.commit()
            logger.info(
                f"Challenge {challenge_id[:8]}... attempt {new_attempt}/{challenge.max_attempts} queued"
            )
            return True

    async def cancel(self, challenge_id: str, reason: str) -> None:
        """Cancel a queued challenge."""
        challenge = await self.get_by_id(challenge_id)
        if challenge:
            failure_reasons = list(challenge.failure_reasons or [])
            failure_reasons.append(f"CANCELLED: {reason}")

            async with self.session_factory() as db:
                await db.execute(
                    update(BlockedChallenge)
                    .where(BlockedChallenge.id == challenge_id)
                    .values(
                        status=ChallengeStatus.CANCELLED.value,
                        failure_reasons=failure_reasons,
                        updated_at=datetime.now(timezone.utc)
                    )
                )
                await db.commit()
            logger.info(f"Challenge {challenge_id[:8]}... CANCELLED: {reason}")

    async def get_pending_count(self) -> int:
        """Get count of challenges awaiting processing."""
        async with self.session_factory() as db:
            result = await db.execute(
                select(BlockedChallenge)
                .where(BlockedChallenge.status.in_([
                    ChallengeStatus.QUEUED.value,
                    ChallengeStatus.BUILDING.value
                ]))
            )
            return len(result.scalars().all())

    async def get_failed_challenges(
        self,
        project_id: Optional[str] = None,
        limit: int = 10
    ) -> list[BlockedChallenge]:
        """Get recently failed challenges for review."""
        async with self.session_factory() as db:
            query = select(BlockedChallenge).where(
                BlockedChallenge.status == ChallengeStatus.FAILED.value
            )
            if project_id:
                query = query.where(BlockedChallenge.project_id == project_id)

            query = query.order_by(BlockedChallenge.updated_at.desc()).limit(limit)
            result = await db.execute(query)
            return list(result.scalars().all())
