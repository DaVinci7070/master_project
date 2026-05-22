"""
Build Plan Service for generating capability build plans.

Analyzes gaps and creates actionable build plans for user approval
or automatic execution (when auto_apply is enabled).
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.schemas.analysis_schemas import CapabilityGap, GapType, GapSeverity
from app.models.schemas.intervention_schemas import (
    BuildPlan, BuildPlanItem, BuildActionType, BuildPlanStatus
)
from app.models.sql.intervention_models import BlockedChallenge, UserSettings

logger = logging.getLogger(__name__)

# Default user ID for single-user mode
DEFAULT_USER_ID = "default"


class BuildPlanService:
    """
    Service for generating and managing build plans.

    Converts capability gaps into actionable build plans that can be:
    - Presented to user for approval
    - Automatically executed (when auto_apply is enabled)
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    def generate_plan_from_gaps(
        self,
        challenge_id: str,
        gaps: list[dict]
    ) -> BuildPlan:
        """
        Generate a build plan from capability gaps.

        Args:
            challenge_id: ID of the challenge
            gaps: List of gap dicts from assessment

        Returns:
            BuildPlan ready for approval or execution
        """
        items: list[BuildPlanItem] = []
        critical_count = 0

        for gap in gaps:
            gap_type = gap.get("gap_type", "missing_skill")
            severity = gap.get("severity", "important")
            affected_cap = gap.get("affected_capability", "unknown")
            description = gap.get("description", "")

            if severity == "critical":
                critical_count += 1

            # Map gap type to build action
            action_type = self._map_gap_to_action(gap_type)

            # Generate human-readable description
            action_description = self._generate_action_description(
                action_type, affected_cap, description
            )

            # Estimate complexity based on gap type and severity
            complexity = self._estimate_complexity(gap_type, severity)

            item = BuildPlanItem(
                action_type=action_type,
                target_capability=affected_cap,
                description=action_description,
                estimated_complexity=complexity,
                affected_agents=[],  # Will be populated during execution
                gap_severity=severity
            )
            items.append(item)

        plan = BuildPlan(
            challenge_id=challenge_id,
            items=items,
            total_gaps=len(gaps),
            critical_gaps=critical_count,
            confidence_after_build="CAN_DO (expected)" if critical_count == 0 else "MAYBE → CAN_DO",
            created_at=datetime.now(timezone.utc)
        )

        logger.info(
            f"Generated build plan for challenge {challenge_id}: "
            f"{len(items)} items, {critical_count} critical"
        )

        return plan

    def _map_gap_to_action(self, gap_type: str) -> BuildActionType:
        """Map gap type to appropriate build action."""
        mapping = {
            "missing_skill": BuildActionType.CREATE_SKILL,
            "weak_prompt": BuildActionType.IMPROVE_PROMPT,
            "missing_agent": BuildActionType.CREATE_AGENT,
            "topology_issue": BuildActionType.UPDATE_TOPOLOGY,
            "schema_mismatch": BuildActionType.CREATE_SKILL,
        }
        return mapping.get(gap_type, BuildActionType.CREATE_SKILL)

    def _generate_action_description(
        self,
        action_type: BuildActionType,
        capability: str,
        gap_description: str
    ) -> str:
        """Generate human-readable description for build action."""
        templates = {
            BuildActionType.CREATE_SKILL: f"Neuen Skill erstellen für: {capability}",
            BuildActionType.IMPROVE_PROMPT: f"Prompt verbessern für: {capability}",
            BuildActionType.CREATE_AGENT: f"Neuen Agent erstellen mit Capability: {capability}",
            BuildActionType.UPDATE_TOPOLOGY: f"Topologie aktualisieren: {capability}",
        }
        base = templates.get(action_type, f"Build: {capability}")

        if gap_description:
            base += f" ({gap_description[:50]}...)" if len(gap_description) > 50 else f" ({gap_description})"

        return base

    def _estimate_complexity(self, gap_type: str, severity: str) -> str:
        """Estimate complexity of build action."""
        if gap_type == "missing_agent":
            return "high"
        elif gap_type == "missing_skill" and severity == "critical":
            return "high"
        elif gap_type in ("weak_prompt", "schema_mismatch"):
            return "low"
        else:
            return "medium"

    async def save_plan_to_challenge(
        self,
        challenge_id: str,
        plan: BuildPlan
    ) -> bool:
        """Save generated plan to challenge record."""
        stmt = select(BlockedChallenge).where(BlockedChallenge.id == challenge_id)
        result = await self.db.execute(stmt)
        challenge = result.scalar_one_or_none()

        if not challenge:
            logger.error(f"Challenge not found: {challenge_id}")
            return False

        challenge.build_plan = plan.model_dump(mode="json")
        challenge.build_plan_status = BuildPlanStatus.PENDING.value
        await self.db.commit()

        logger.info(f"Saved build plan to challenge {challenge_id}")
        return True

    async def update_plan_status(
        self,
        challenge_id: str,
        status: BuildPlanStatus
    ) -> bool:
        """Update build plan status."""
        stmt = select(BlockedChallenge).where(BlockedChallenge.id == challenge_id)
        result = await self.db.execute(stmt)
        challenge = result.scalar_one_or_none()

        if not challenge:
            return False

        challenge.build_plan_status = status.value
        await self.db.commit()
        return True

    async def get_user_settings(self, user_id: str = DEFAULT_USER_ID) -> UserSettings:
        """Get user settings, creating default if not exists."""
        stmt = select(UserSettings).where(UserSettings.user_id == user_id)
        result = await self.db.execute(stmt)
        settings = result.scalar_one_or_none()

        if not settings:
            # Create default settings
            settings = UserSettings(
                user_id=user_id,
                auto_apply=False,
                notify_on_build=True,
                notify_on_execution=True
            )
            self.db.add(settings)
            await self.db.commit()
            await self.db.refresh(settings)

        return settings

    async def update_user_settings(
        self,
        user_id: str = DEFAULT_USER_ID,
        auto_apply: Optional[bool] = None,
        notify_on_build: Optional[bool] = None,
        notify_on_execution: Optional[bool] = None
    ) -> UserSettings:
        """Update user settings."""
        settings = await self.get_user_settings(user_id)

        if auto_apply is not None:
            settings.auto_apply = auto_apply
        if notify_on_build is not None:
            settings.notify_on_build = notify_on_build
        if notify_on_execution is not None:
            settings.notify_on_execution = notify_on_execution

        await self.db.commit()
        await self.db.refresh(settings)

        logger.info(f"Updated settings for user {user_id}: auto_apply={settings.auto_apply}")
        return settings

    async def is_auto_apply_enabled(self, user_id: str = DEFAULT_USER_ID) -> bool:
        """Check if auto-apply is enabled for user."""
        settings = await self.get_user_settings(user_id)
        return settings.auto_apply
