"""Capability matching using semantic similarity."""
import logging
import os
import re
from typing import Callable, Awaitable, Optional
import numpy as np

from app.orchestration.topology.loader import TopologyLoader
from app.orchestration.analysis.models import (
    CapabilityMatch, CapabilityType, TopologyCapabilities
)

logger = logging.getLogger(__name__)

# Thresholds (configurable via ENV)
# Lowered from 0.95 to 0.90 - 0.95 was too strict and caused false negatives
CAN_DO_THRESHOLD = float(os.getenv("CAPABILITY_CAN_DO_THRESHOLD", "0.90"))
MAYBE_THRESHOLD = float(os.getenv("CAPABILITY_MAYBE_THRESHOLD", "0.50"))

# Direct match score (bypasses embedding comparison)
DIRECT_MATCH_SCORE = 1.0


class CapabilityMatcher:
    """
    Match required capabilities against topology using semantic similarity.

    Uses embedding similarity to find best matches between what a challenge
    needs and what the system's agents provide.
    """

    def __init__(
        self,
        topology_loader: TopologyLoader,
        embedding_fn: Optional[Callable[[str], Awaitable[list[float]]]] = None
    ):
        """
        Initialize capability matcher.

        Args:
            topology_loader: Loader for current system topology
            embedding_fn: Function to generate embeddings (text -> vector)
        """
        self.topology = topology_loader
        self._get_embedding = embedding_fn
        self._embedding_cache: dict[str, list[float]] = {}

    async def _get_cached_embedding(self, text: str) -> list[float]:
        """Get embedding with caching for repeated capability strings."""
        if text not in self._embedding_cache:
            if self._get_embedding:
                self._embedding_cache[text] = await self._get_embedding(text)
            else:
                # Fallback: zero vector (development mode)
                # Using 768 dimensions to match Gemini embeddings
                logger.warning(f"No embedding function configured, using zero vector for: {text[:50]}")
                self._embedding_cache[text] = [0.0] * 768
        return self._embedding_cache[text]

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        a_arr, b_arr = np.array(a), np.array(b)
        norm_a, norm_b = np.linalg.norm(a_arr), np.linalg.norm(b_arr)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))

    def _normalize_capability(self, name: str) -> str:
        """
        Normalize capability name for direct string matching.

        Handles variations like:
        - "Financial Calculation" -> "financial calculation"
        - "risk assessment (downtime costs)" -> "risk assessment"
        - "Cost_Analysis" -> "cost analysis"
        - "data-analysis" -> "data analysis"
        """
        # Lowercase and strip
        normalized = name.lower().strip()
        # Remove content in parentheses
        normalized = re.sub(r'\s*\([^)]*\)', '', normalized)
        # Replace underscores/hyphens with spaces
        normalized = normalized.replace('_', ' ').replace('-', ' ')
        # Normalize whitespace
        normalized = ' '.join(normalized.split())
        return normalized

    def _check_direct_match(
        self,
        required: str,
        available_caps: list[str]
    ) -> Optional[str]:
        """
        Check for direct string match (normalized) between required and available.

        Returns the matched capability string if found, None otherwise.
        """
        req_normalized = self._normalize_capability(required)

        for avail in available_caps:
            avail_normalized = self._normalize_capability(avail)

            # Exact match after normalization
            if req_normalized == avail_normalized:
                return avail

            # Check if one contains the other (for partial matches)
            # e.g., "financial calculation" matches "financial calculation skills"
            if req_normalized in avail_normalized or avail_normalized in req_normalized:
                # Only if significant overlap (at least 70% of shorter string)
                shorter = min(len(req_normalized), len(avail_normalized))
                longer = max(len(req_normalized), len(avail_normalized))
                if shorter / longer >= 0.7:
                    return avail

        return None

    async def extract_topology_capabilities(self) -> TopologyCapabilities:
        """
        Extract all capabilities from current topology.

        Returns TopologyCapabilities with agent-capability mapping.

        Capability sources (in order of priority):
        1. Agent capabilities (explicitly declared)
        2. Skill capabilities (from affected_capability metadata)
        3. Prompt capabilities (from affected_capability metadata) - NEW

        This ensures newly built skills AND prompts are discoverable during re-assessment.
        """
        topology, validation = await self.topology.load()

        agent_capabilities: dict[str, list[str]] = {}
        all_capabilities: set[str] = set()

        for agent in topology.get_active_agents():
            caps = agent.capabilities or []
            agent_capabilities[agent.agent_id] = caps
            all_capabilities.update(caps)

        # Include capabilities from active skills (even if unbound)
        skill_capabilities = await self._extract_skill_capabilities()
        for skill_id, skill_caps in skill_capabilities.items():
            agent_capabilities[f"skill:{skill_id}"] = skill_caps
            all_capabilities.update(skill_caps)

        # NEW: Include capabilities from prompts with affected_capability
        # This allows weak_prompt builds to be recognized as fulfilling capabilities
        prompt_capabilities = await self._extract_prompt_capabilities()
        for prompt_id, prompt_caps in prompt_capabilities.items():
            agent_capabilities[f"prompt:{prompt_id}"] = prompt_caps
            all_capabilities.update(prompt_caps)

        return TopologyCapabilities(
            agent_capabilities=agent_capabilities,
            all_capabilities=all_capabilities,
            active_agent_count=len(topology.get_active_agents()),
            skill_count=len(self.topology.get_all_loaded_skills()) + len(skill_capabilities),
            has_dependency_issues=not validation.is_valid,
            dependency_issues=validation.errors if not validation.is_valid else []
        )

    async def _extract_skill_capabilities(self) -> dict[str, list[str]]:
        """
        Extract capabilities from active skills in database.

        Skills provide capabilities through (priority order):
        1. skill_metadata.affected_capability (PRIMARY - what gap it was built to fill)
        2. skill_metadata.capability_name (explicit capability name)
        3. name (e.g., "skill_financial_calculation" -> "financial calculation")

        Note: affected_capability is the most important as it directly maps to
        the gap that was identified during capability assessment.
        """
        from sqlalchemy import select
        from app.models.sql.versioned_models import Skill

        # Access db through topology loader
        db = self.topology.db

        result = await db.execute(
            select(Skill).where(Skill.is_active == True)
        )
        skills = result.scalars().all()

        skill_capabilities: dict[str, list[str]] = {}

        for skill in skills:
            caps = []

            # PRIMARY: affected_capability from metadata (most important!)
            # This is set by CapabilityBuilder when filling a gap
            if skill.skill_metadata:
                if affected_cap := skill.skill_metadata.get("affected_capability"):
                    caps.append(affected_cap)
                    logger.info(
                        f"Skill '{skill.name}' provides affected_capability: '{affected_cap}'"
                    )

                # Secondary: explicit capability_name
                if cap_name := skill.skill_metadata.get("capability_name"):
                    if cap_name not in caps:
                        caps.append(cap_name)

            # Fallback: derive from skill name
            if skill.name and not caps:
                derived_cap = skill.name.replace("skill_", "").replace("_", " ")
                caps.append(derived_cap)

            if caps:
                skill_capabilities[skill.id] = caps

        if skill_capabilities:
            total_caps = sum(len(c) for c in skill_capabilities.values())
            logger.info(
                f"Extracted {total_caps} capabilities from {len(skill_capabilities)} active skills"
            )

        return skill_capabilities

    async def _extract_prompt_capabilities(self) -> dict[str, list[str]]:
        """
        Extract capabilities from active prompts in database.

        Prompts provide capabilities through:
        1. prompt_metadata.affected_capability (PRIMARY - what gap it was built to fill)
        2. prompt_metadata.capability_name (explicit capability name)

        This allows weak_prompt gap builds to be recognized as fulfilling capabilities.
        Without this, building a prompt for "risk assessment" would never close the gap.
        """
        from sqlalchemy import select
        from app.models.sql.versioned_models import Prompt

        db = self.topology.db

        result = await db.execute(
            select(Prompt).where(Prompt.is_active == True)
        )
        prompts = result.scalars().all()

        prompt_capabilities: dict[str, list[str]] = {}

        for prompt in prompts:
            caps = []

            if prompt.prompt_metadata:
                # PRIMARY: affected_capability from metadata
                # This is set when building prompts for gaps
                if affected_cap := prompt.prompt_metadata.get("affected_capability"):
                    caps.append(affected_cap)
                    logger.info(
                        f"Prompt '{prompt.name}' provides affected_capability: '{affected_cap}'"
                    )

                # Secondary: explicit capability_name
                if cap_name := prompt.prompt_metadata.get("capability_name"):
                    if cap_name not in caps:
                        caps.append(cap_name)

            if caps:
                prompt_capabilities[prompt.id] = caps

        if prompt_capabilities:
            total_caps = sum(len(c) for c in prompt_capabilities.values())
            logger.info(
                f"Extracted {total_caps} capabilities from {len(prompt_capabilities)} active prompts"
            )

        return prompt_capabilities

    async def match_capabilities(
        self,
        required_capabilities: list[str],
        topology_capabilities: TopologyCapabilities,
        capability_types: Optional[dict[str, CapabilityType]] = None
    ) -> list[CapabilityMatch]:
        """
        Match each required capability against available capabilities.

        Uses a two-phase matching approach:
        1. Direct string match (normalized) - instant match with score 1.0
        2. Embedding-based semantic similarity - for fuzzy matching

        Args:
            required_capabilities: Capabilities needed for the challenge
            topology_capabilities: Available capabilities from topology
            capability_types: Optional mapping of capability name to type (knowledge/execution)

        Returns:
            List of CapabilityMatch with similarity scores and type info
        """
        matches = []
        capability_types = capability_types or {}

        # Flatten all available capabilities for direct matching
        all_available_caps = list(topology_capabilities.all_capabilities)

        for req_cap in required_capabilities:
            best_score = 0.0
            best_match: Optional[str] = None
            best_agent: Optional[str] = None
            match_type = "none"

            # PHASE 1: Direct string match (normalized)
            # This catches exact matches like "financial calculation" == "financial calculation"
            direct_match = self._check_direct_match(req_cap, all_available_caps)

            if direct_match:
                # Find which agent/skill provides this capability
                for agent_id, caps in topology_capabilities.agent_capabilities.items():
                    if direct_match in caps or self._check_direct_match(direct_match, caps):
                        best_score = DIRECT_MATCH_SCORE
                        best_match = direct_match
                        best_agent = agent_id
                        match_type = "direct"
                        logger.info(
                            f"DIRECT MATCH: '{req_cap}' -> '{direct_match}' "
                            f"(provider: {agent_id})"
                        )
                        break

            # PHASE 2: Embedding-based matching (if no direct match found)
            if best_score < DIRECT_MATCH_SCORE:
                req_embedding = await self._get_cached_embedding(req_cap)

                # Find best matching capability across all agents
                for agent_id, caps in topology_capabilities.agent_capabilities.items():
                    for topo_cap in caps:
                        topo_embedding = await self._get_cached_embedding(topo_cap)
                        similarity = self._cosine_similarity(req_embedding, topo_embedding)

                        if similarity > best_score:
                            best_score = similarity
                            best_match = topo_cap
                            best_agent = agent_id
                            match_type = "embedding"

            # Determine if match is sufficient
            is_sufficient = best_score >= CAN_DO_THRESHOLD

            # Get capability type (defaults to KNOWLEDGE for backward compatibility)
            cap_type = capability_types.get(req_cap, CapabilityType.KNOWLEDGE)

            match = CapabilityMatch(
                required_capability=req_cap,
                capability_type=cap_type,
                matched_capability=best_match,
                similarity_score=best_score,
                matched_agent_id=best_agent,
                is_sufficient=is_sufficient
            )
            matches.append(match)

            logger.debug(
                f"Capability match: '{req_cap}' [{cap_type.value}] -> '{best_match}' "
                f"(score={best_score:.3f}, type={match_type}, sufficient={is_sufficient})"
            )

        return matches

    def clear_cache(self) -> None:
        """Clear embedding cache (call between analysis sessions)."""
        self._embedding_cache.clear()
