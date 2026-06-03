import logging
import re
from datetime import datetime, timezone
from typing import Optional, List, Tuple

from sqlalchemy import select

from app.models.sql.versioned_models import Skill, Prompt, Agent
from app.models.schemas.verification_schemas import (
    GapVerificationResult,
    PlanVerificationResult,
    CapabilityExistsResult,
)
from app.orchestration.execution.gap_plan import GapPlanService

logger = logging.getLogger(__name__)


class GapVerificationService:
    """
    Service for verifying gap closure without LLM re-analysis.

    Verification logic:
    1. For each gap, search for artifacts with matching affected_capability
    2. Check Skills, Prompts, and Agents
    3. Use normalized string matching (case-insensitive, whitespace-normalized)
    4. Return deterministic results
    """

    def __init__(self, session_factory):
        self.session_factory = session_factory
        self.plan_service = GapPlanService(session_factory)

    def _normalize_capability(self, name: str) -> str:
        """
        Normalize capability name for matching.

        Handles:
        - Case: "Financial Calculation" -> "financial calculation"
        - Underscores: "financial_calculation" -> "financial calculation"
        - Hyphens: "financial-calculation" -> "financial calculation"
        - Extra whitespace: "financial   calculation" -> "financial calculation"
        - Parentheses content: "risk assessment (downtime)" -> "risk assessment"
        """
        normalized = name.lower().strip()
        normalized = re.sub(r'\s*\([^)]*\)', '', normalized)
        normalized = normalized.replace('_', ' ').replace('-', ' ')
        normalized = ' '.join(normalized.split())
        return normalized

    def _calculate_word_overlap(self, str1: str, str2: str) -> float:
        """Calculate word overlap score between two strings."""
        words1 = set(self._normalize_capability(str1).split())
        words2 = set(self._normalize_capability(str2).split())

        if not words1 or not words2:
            return 0.0

        intersection = len(words1 & words2)
        union = len(words1 | words2)

        return intersection / union if union > 0 else 0.0

    def _match_capability(
        self,
        required: str,
        available: str
    ) -> Tuple[bool, str, float]:
        """
        Check if available capability matches required capability.

        Returns:
            Tuple of (matches, match_type, score)
        """
        req_norm = self._normalize_capability(required)
        avail_norm = self._normalize_capability(available)

        if req_norm == avail_norm:
            return True, "exact", 1.0

        if req_norm in avail_norm or avail_norm in req_norm:
            shorter = min(len(req_norm), len(avail_norm))
            longer = max(len(req_norm), len(avail_norm))
            score = shorter / longer if longer > 0 else 0
            if score >= 0.6:
                return True, "contains", score

        overlap_score = self._calculate_word_overlap(required, available)
        if overlap_score >= 0.5:
            return True, "word_overlap", overlap_score

        return False, "none", 0.0

    async def _get_agent_capabilities(self, agent, db) -> list[str]:
        """Derive agent capabilities from assigned skills' applicability fields."""
        skills = (await db.execute(
            select(Skill).where(Skill.is_active == True)
        )).scalars().all()

        caps = []
        for skill in skills:
            meta = skill.skill_metadata or {}
            target = meta.get("target_agent_id") or meta.get("assigned_agent")
            if target and target != agent.id and target != agent.name:
                continue
            if skill.applicability:
                caps.append(skill.applicability)
            elif meta.get("affected_capability"):
                caps.append(meta["affected_capability"])
        return caps

    async def capability_exists(
        self,
        capability_name: str
    ) -> CapabilityExistsResult:
        """
        Check if a capability exists in the system.

        Searches in order:
        1. Skills with affected_capability in metadata
        2. Skills by name (fallback - skill names often derived from capabilities)
        3. Prompts with affected_capability in metadata
        4. Agents with capability in capabilities list

        Args:
            capability_name: The capability to search for

        Returns:
            CapabilityExistsResult with provider details if found
        """
        async with self.session_factory() as db:
            result = await db.execute(
                select(Skill).where(Skill.is_active == True)
            )
            skills = result.scalars().all()

            for skill in skills:
                if skill.skill_metadata:
                    affected_cap = skill.skill_metadata.get("affected_capability")
                    if affected_cap:
                        matches, match_type, score = self._match_capability(
                            capability_name, affected_cap
                        )
                        if matches:
                            logger.debug(
                                f"Capability '{capability_name}' found in skill '{skill.name}' "
                                f"(match_type={match_type}, score={score:.2f})"
                            )
                            return CapabilityExistsResult(
                                capability_name=capability_name,
                                exists=True,
                                provider_id=skill.id,
                                provider_type="skill",
                                provider_name=skill.name,
                                matched_capability=affected_cap,
                                match_type=match_type,
                                match_score=score,
                            )

                skill_name_normalized = skill.name.replace("skill_", "").replace("_", " ")
                matches, match_type, score = self._match_capability(
                    capability_name, skill_name_normalized
                )
                if matches and score >= 0.7:
                    logger.debug(
                        f"Capability '{capability_name}' found by skill name '{skill.name}' "
                        f"(match_type=name_{match_type}, score={score:.2f})"
                    )
                    return CapabilityExistsResult(
                        capability_name=capability_name,
                        exists=True,
                        provider_id=skill.id,
                        provider_type="skill",
                        provider_name=skill.name,
                        matched_capability=skill_name_normalized,
                        match_type=f"name_{match_type}",
                        match_score=score,
                    )

            result = await db.execute(
                select(Prompt).where(Prompt.is_active == True)
            )
            prompts = result.scalars().all()

            for prompt in prompts:
                if prompt.prompt_metadata:
                    affected_cap = prompt.prompt_metadata.get("affected_capability")
                    if affected_cap:
                        matches, match_type, score = self._match_capability(
                            capability_name, affected_cap
                        )
                        if matches:
                            logger.debug(
                                f"Capability '{capability_name}' found in prompt '{prompt.name}' "
                                f"(match_type={match_type}, score={score:.2f})"
                            )
                            return CapabilityExistsResult(
                                capability_name=capability_name,
                                exists=True,
                                provider_id=prompt.id,
                                provider_type="prompt",
                                provider_name=prompt.name,
                                matched_capability=affected_cap,
                                match_type=match_type,
                                match_score=score,
                            )

            result = await db.execute(
                select(Agent).where(Agent.is_active == True)
            )
            agents = result.scalars().all()

            for agent in agents:
                agent_caps = await self._get_agent_capabilities(agent, db)
                for agent_cap in agent_caps:
                    matches, match_type, score = self._match_capability(
                        capability_name, agent_cap
                    )
                    if matches:
                        logger.debug(
                            f"Capability '{capability_name}' found in agent '{agent.name}' "
                            f"(match_type={match_type}, score={score:.2f})"
                        )
                        return CapabilityExistsResult(
                            capability_name=capability_name,
                            exists=True,
                            provider_id=agent.id,
                            provider_type="agent",
                            provider_name=agent.name,
                            matched_capability=agent_cap,
                            match_type=match_type,
                            match_score=score,
                        )

            logger.debug(f"Capability '{capability_name}' not found in system")
            return CapabilityExistsResult(
                capability_name=capability_name,
                exists=False,
            )

    async def verify_gap_closure(
        self,
        gap: dict
    ) -> GapVerificationResult:
        """
        Verify if a single gap has been closed.

        Args:
            gap: Gap dict from plan (must have 'id' and 'affected_capability')

        Returns:
            GapVerificationResult indicating if gap is closed
        """
        gap_id = gap.get("id", "unknown")
        affected_capability = gap.get("affected_capability", "")

        if not affected_capability:
            logger.warning(f"Gap {gap_id} has no affected_capability")
            return GapVerificationResult(
                gap_id=gap_id,
                affected_capability="",
                is_closed=False,
                verification_method="database_lookup",
            )

        exists_result = await self.capability_exists(affected_capability)

        if exists_result.exists:
            return GapVerificationResult(
                gap_id=gap_id,
                affected_capability=affected_capability,
                is_closed=True,
                closed_by_artifact_id=exists_result.provider_id,
                closed_by_artifact_type=exists_result.provider_type,
                match_type=exists_result.match_type,
                match_score=exists_result.match_score,
                verification_method="database_lookup",
            )
        else:
            return GapVerificationResult(
                gap_id=gap_id,
                affected_capability=affected_capability,
                is_closed=False,
                verification_method="database_lookup",
            )

    async def verify_plan_completion(
        self,
        plan_id: str
    ) -> PlanVerificationResult:
        """
        Verify if all gaps in a plan have been closed.

        This is the main entry point for post-build verification.
        Does NOT call LLM - only database lookups.

        Args:
            plan_id: ID of the gap plan to verify

        Returns:
            PlanVerificationResult with closure status for each gap
        """
        plan = await self.plan_service.get_plan(plan_id)

        if not plan:
            logger.error(f"Plan not found for verification: {plan_id}")
            return PlanVerificationResult(
                plan_id=plan_id,
                all_closed=False,
                total_gaps=0,
                closed_count=0,
                open_count=0,
                open_gaps=[],
                verification_details=[],
            )

        gaps = plan.gaps or []
        verification_details: List[GapVerificationResult] = []
        open_gaps: List[dict] = []
        closed_count = 0

        for gap in gaps:
            result = await self.verify_gap_closure(gap)
            verification_details.append(result)

            if result.is_closed:
                closed_count += 1
                logger.info(
                    f"Gap CLOSED: '{result.affected_capability}' "
                    f"by {result.closed_by_artifact_type}/{result.closed_by_artifact_id[:8] if result.closed_by_artifact_id else 'N/A'}..."
                )
            else:
                open_gaps.append(gap)
                logger.info(
                    f"Gap OPEN: '{result.affected_capability}'"
                )

        all_closed = closed_count == len(gaps)
        open_count = len(gaps) - closed_count

        logger.info(
            f"Plan verification complete: {plan_id[:8]}..., "
            f"closed={closed_count}/{len(gaps)}, all_closed={all_closed}"
        )

        return PlanVerificationResult(
            plan_id=plan_id,
            all_closed=all_closed,
            total_gaps=len(gaps),
            closed_count=closed_count,
            open_count=open_count,
            open_gaps=open_gaps,
            verification_details=verification_details,
            verified_at=datetime.now(timezone.utc).isoformat(),
        )

    async def verify_capabilities_for_challenge(
        self,
        required_capabilities: List[str]
    ) -> Tuple[bool, List[str], List[str]]:
        """
        Verify if all required capabilities exist.

        Useful for quick checks without a plan.

        Args:
            required_capabilities: List of capability names needed

        Returns:
            Tuple of (all_exist, found_caps, missing_caps)
        """
        found = []
        missing = []

        for cap in required_capabilities:
            result = await self.capability_exists(cap)
            if result.exists:
                found.append(cap)
            else:
                missing.append(cap)

        return len(missing) == 0, found, missing
