import logging
import os
from typing import Callable, Awaitable, Optional
import numpy as np

from app.orchestration.topology.loader import TopologyLoader
from app.orchestration.analysis.models import (
    CapabilityMatch, CapabilityType, TopologyCapabilities
)

logger = logging.getLogger(__name__)

CAN_DO_THRESHOLD = float(os.getenv("CAPABILITY_CAN_DO_THRESHOLD", "0.90"))
MAYBE_THRESHOLD = float(os.getenv("CAPABILITY_MAYBE_THRESHOLD", "0.50"))

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
            embedding_fn: Function to generate embeddings (text -> vector).
                          Defaults to fastembed (BAAI/bge-base-en-v1.5) if not provided.
        """
        self.topology = topology_loader
        if embedding_fn is None:
            from app.core.llm_client import get_embedding
            self._get_embedding = get_embedding
        else:
            self._get_embedding = embedding_fn
        self._embedding_cache: dict[str, list[float]] = {}

    async def _get_cached_embedding(self, text: str) -> list[float]:
        """Get embedding with caching for repeated capability strings."""
        if text not in self._embedding_cache:
            self._embedding_cache[text] = await self._get_embedding(text)
        return self._embedding_cache[text]

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        a_arr, b_arr = np.array(a), np.array(b)
        norm_a, norm_b = np.linalg.norm(a_arr), np.linalg.norm(b_arr)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))

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
            caps = list(agent.capabilities) if agent.capabilities else []
            agent_capabilities[agent.agent_id] = caps
            all_capabilities.update(caps)

        skill_capabilities = await self._extract_skill_capabilities()
        for skill_id, skill_caps in skill_capabilities.items():
            agent_capabilities[f"skill:{skill_id}"] = skill_caps
            all_capabilities.update(skill_caps)

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

        async with self.topology.session_factory() as db:
            result = await db.execute(
                select(Skill).where(Skill.is_active == True)
            )
            skills = result.scalars().all()

        skill_capabilities: dict[str, list[str]] = {}

        for skill in skills:
            caps = []

            if skill.applicability:
                caps.append(skill.applicability)
                logger.info(
                    f"Skill '{skill.name}' provides applicability: '{skill.applicability}'"
                )

            if not caps and skill.skill_metadata:
                if affected_cap := skill.skill_metadata.get("affected_capability"):
                    caps.append(affected_cap)
                    logger.info(
                        f"Skill '{skill.name}' provides affected_capability: '{affected_cap}'"
                    )

                if cap_name := skill.skill_metadata.get("capability_name"):
                    if cap_name not in caps:
                        caps.append(cap_name)

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

        async with self.topology.session_factory() as db:
            result = await db.execute(
                select(Prompt).where(Prompt.is_active == True)
            )
            prompts = result.scalars().all()

        prompt_capabilities: dict[str, list[str]] = {}

        for prompt in prompts:
            caps = []

            if prompt.prompt_metadata:
                if affected_cap := prompt.prompt_metadata.get("affected_capability"):
                    caps.append(affected_cap)
                    logger.info(
                        f"Prompt '{prompt.name}' provides affected_capability: '{affected_cap}'"
                    )

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

        Uses embedding-based semantic similarity to find best matches.

        Args:
            required_capabilities: Capabilities needed for the challenge
            topology_capabilities: Available capabilities from topology
            capability_types: Optional mapping of capability name to type (knowledge/execution)

        Returns:
            List of CapabilityMatch with similarity scores and type info
        """
        matches = []
        capability_types = capability_types or {}

        for req_cap in required_capabilities:
            best_score = 0.0
            best_match: Optional[str] = None
            best_agent: Optional[str] = None

            req_embedding = await self._get_cached_embedding(req_cap)

            for agent_id, caps in topology_capabilities.agent_capabilities.items():
                for topo_cap in caps:
                    topo_embedding = await self._get_cached_embedding(topo_cap)
                    similarity = self._cosine_similarity(req_embedding, topo_embedding)

                    if similarity > best_score:
                        best_score = similarity
                        best_match = topo_cap
                        best_agent = agent_id

            is_sufficient = best_score >= CAN_DO_THRESHOLD
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
                f"(score={best_score:.3f}, sufficient={is_sufficient})"
            )

        return matches

    def clear_cache(self) -> None:
        """Clear embedding cache (call between analysis sessions)."""
        self._embedding_cache.clear()
