"""
Gap Plan Service for deterministic capability gap resolution.

This service manages the lifecycle of capability gap plans:
1. Create plan from initial assessment
2. Track progress as gaps are built
3. Complete/fail plan based on results

Key design: Gap list is FIXED at creation time - no re-analysis during execution.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, and_

from app.models.sql.gap_plan_models import CapabilityGapPlan, GapPlanStatus, GapStatus
from app.models.schemas.analysis_schemas import CapabilityGap, CapabilityAssessment

logger = logging.getLogger(__name__)


class GapPlanService:
    """
    Service for managing capability gap plans.

    Gap plans ensure deterministic behavior by:
    - Fixing the gap list at creation (no re-analysis during build)
    - Tracking progress per gap
    - Supporting retry cycles (max 3)
    """

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def create_plan(
        self,
        challenge_id: str,
        gaps: list[CapabilityGap],
        execution_id: Optional[str] = None,
        assessment: Optional[CapabilityAssessment] = None,
        cycle_number: int = 1
    ) -> CapabilityGapPlan:
        """
        Create a new gap plan from identified gaps.

        Args:
            challenge_id: ID of the challenge
            gaps: List of CapabilityGap objects from assessment
            execution_id: Optional execution ID
            assessment: Full assessment for reference
            cycle_number: Cycle number (1, 2, 3 for retries)

        Returns:
            Created CapabilityGapPlan
        """
        # Convert gaps to JSON-serializable format
        gaps_json = []
        for gap in gaps:
            gap_dict = {
                "id": str(uuid.uuid4()),
                "gap_type": gap.gap_type.value if hasattr(gap.gap_type, 'value') else str(gap.gap_type),
                "affected_capability": gap.affected_capability,
                "severity": gap.severity.value if hasattr(gap.severity, 'value') else str(gap.severity),
                "description": gap.description,
                "status": GapStatus.PENDING.value,
                "artifact_id": None,
                "artifact_type": None,
                "error_message": None,
                "started_at": None,
                "completed_at": None,
            }
            gaps_json.append(gap_dict)

        # Sort by severity (critical first)
        severity_order = {"critical": 0, "important": 1, "minor": 2}
        gaps_json.sort(key=lambda g: severity_order.get(g["severity"], 2))

        # Create plan
        plan = CapabilityGapPlan(
            id=str(uuid.uuid4()),
            challenge_id=challenge_id,
            execution_id=execution_id,
            cycle_number=cycle_number,
            status=GapPlanStatus.PENDING.value,
            gaps=gaps_json,
            total_gaps=len(gaps_json),
            completed_gaps=0,
            failed_gaps=0,
            initial_confidence=assessment.confidence.value if assessment else None,
            initial_assessment=assessment.model_dump() if assessment else None,
        )

        async with self.session_factory() as db:
            db.add(plan)
            await db.commit()
            await db.refresh(plan)

        logger.info(
            f"Created gap plan: id={plan.id[:8]}..., "
            f"challenge={challenge_id[:8]}..., "
            f"gaps={len(gaps_json)}, cycle={cycle_number}"
        )

        return plan

    async def get_plan(self, plan_id: str) -> Optional[CapabilityGapPlan]:
        """Get gap plan by ID."""
        async with self.session_factory() as db:
            result = await db.execute(
                select(CapabilityGapPlan).where(CapabilityGapPlan.id == plan_id)
            )
            return result.scalar_one_or_none()

    async def get_active_plan(self, challenge_id: str) -> Optional[CapabilityGapPlan]:
        """
        Get active (non-completed) plan for a challenge.

        Returns the most recent non-completed plan.
        """
        async with self.session_factory() as db:
            result = await db.execute(
                select(CapabilityGapPlan)
                .where(
                    and_(
                        CapabilityGapPlan.challenge_id == challenge_id,
                        CapabilityGapPlan.status.in_([
                            GapPlanStatus.PENDING.value,
                            GapPlanStatus.IN_PROGRESS.value
                        ])
                    )
                )
                .order_by(CapabilityGapPlan.cycle_number.desc())
            )
            return result.scalars().first()

    async def get_latest_plan(self, challenge_id: str) -> Optional[CapabilityGapPlan]:
        """Get the most recent plan for a challenge (any status)."""
        async with self.session_factory() as db:
            result = await db.execute(
                select(CapabilityGapPlan)
                .where(CapabilityGapPlan.challenge_id == challenge_id)
                .order_by(CapabilityGapPlan.created_at.desc())
            )
            return result.scalars().first()

    async def get_plan_history(self, challenge_id: str) -> list[CapabilityGapPlan]:
        """Get all plans for a challenge (all cycles)."""
        async with self.session_factory() as db:
            result = await db.execute(
                select(CapabilityGapPlan)
                .where(CapabilityGapPlan.challenge_id == challenge_id)
                .order_by(CapabilityGapPlan.cycle_number.asc())
            )
            return list(result.scalars().all())

    async def start_plan(self, plan_id: str) -> CapabilityGapPlan:
        """Mark plan as in_progress."""
        async with self.session_factory() as db:
            result = await db.execute(
                select(CapabilityGapPlan).where(CapabilityGapPlan.id == plan_id)
            )
            plan = result.scalar_one_or_none()
            if not plan:
                raise ValueError(f"Plan not found: {plan_id}")

            plan.status = GapPlanStatus.IN_PROGRESS.value
            plan.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(plan)

        logger.info(f"Started gap plan: {plan_id[:8]}...")
        return plan

    async def update_gap_status(
        self,
        plan_id: str,
        gap_id: str,
        status: str,
        artifact_id: Optional[str] = None,
        artifact_type: Optional[str] = None,
        error_message: Optional[str] = None
    ) -> CapabilityGapPlan:
        """
        Update status of a specific gap within a plan.

        Args:
            plan_id: Plan ID
            gap_id: Gap ID within the plan
            status: New status (pending, building, completed, failed, skipped)
            artifact_id: Built artifact ID (for completed)
            artifact_type: Type of artifact (skill, prompt, agent)
            error_message: Error message (for failed)

        Returns:
            Updated plan
        """
        async with self.session_factory() as db:
            result = await db.execute(
                select(CapabilityGapPlan).where(CapabilityGapPlan.id == plan_id)
            )
            plan = result.scalar_one_or_none()
            if not plan:
                raise ValueError(f"Plan not found: {plan_id}")

            # Update the gap
            updated = plan.update_gap_status(
                gap_id=gap_id,
                status=status,
                artifact_id=artifact_id,
                artifact_type=artifact_type,
                error_message=error_message
            )

            if not updated:
                raise ValueError(f"Gap not found in plan: {gap_id}")

            # If plan was pending, mark as in_progress
            if plan.status == GapPlanStatus.PENDING.value:
                plan.status = GapPlanStatus.IN_PROGRESS.value

            plan.updated_at = datetime.now(timezone.utc)

            # Force SQLAlchemy to detect JSON change
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(plan, "gaps")

            await db.commit()
            await db.refresh(plan)

        logger.debug(
            f"Updated gap {gap_id[:8]}... status={status}, "
            f"plan progress: {plan.completed_gaps}/{plan.total_gaps}"
        )

        return plan

    async def get_next_pending_gap(self, plan_id: str) -> Optional[dict]:
        """
        Get next pending gap from plan.

        Returns None if no pending gaps remain.
        """
        plan = await self.get_plan(plan_id)
        if not plan:
            return None

        return plan.get_next_pending_gap()

    async def complete_plan(
        self,
        plan_id: str,
        status: str = GapPlanStatus.COMPLETED.value
    ) -> CapabilityGapPlan:
        """
        Mark plan as completed or failed.

        Args:
            plan_id: Plan ID
            status: Final status (completed or failed)

        Returns:
            Updated plan
        """
        async with self.session_factory() as db:
            result = await db.execute(
                select(CapabilityGapPlan).where(CapabilityGapPlan.id == plan_id)
            )
            plan = result.scalar_one_or_none()
            if not plan:
                raise ValueError(f"Plan not found: {plan_id}")

            plan.status = status
            plan.completed_at = datetime.now(timezone.utc)
            plan.updated_at = datetime.now(timezone.utc)

            await db.commit()
            await db.refresh(plan)

        logger.info(
            f"Completed gap plan: {plan_id[:8]}..., status={status}, "
            f"completed={plan.completed_gaps}, failed={plan.failed_gaps}"
        )

        return plan

    async def should_create_new_cycle(
        self,
        challenge_id: str,
        max_cycles: int = 3
    ) -> tuple[bool, int]:
        """
        Check if a new cycle should be created.

        Returns (should_create, next_cycle_number)
        """
        latest = await self.get_latest_plan(challenge_id)

        if not latest:
            return True, 1

        if latest.status in (GapPlanStatus.PENDING.value, GapPlanStatus.IN_PROGRESS.value):
            # Active plan exists, don't create new
            return False, latest.cycle_number

        if latest.cycle_number >= max_cycles:
            # Max cycles reached
            return False, latest.cycle_number

        # Previous plan completed/failed, can create new cycle
        return True, latest.cycle_number + 1

    async def get_plan_summary(self, plan_id: str) -> dict:
        """Get summary of plan for API response."""
        plan = await self.get_plan(plan_id)
        if not plan:
            return {}

        return plan.to_dict()

    async def get_all_built_artifacts(self, plan_id: str) -> list[dict]:
        """Get list of all successfully built artifacts from plan."""
        plan = await self.get_plan(plan_id)
        if not plan:
            return []

        artifacts = []
        for gap in (plan.gaps or []):
            if gap.get("status") == GapStatus.COMPLETED.value and gap.get("artifact_id"):
                artifacts.append({
                    "artifact_id": gap["artifact_id"],
                    "artifact_type": gap["artifact_type"],
                    "capability": gap["affected_capability"],
                    "gap_type": gap["gap_type"],
                })

        return artifacts
