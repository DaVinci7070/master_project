"""Topology loader from database with validation and caching."""
import logging
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select, update

from app.orchestration.topology.models import Topology, AgentNode, ValidationResult
from app.orchestration.topology.validator import TopologyValidator
from app.repositories.topology_repository import TopologyRepository
from app.models.sql.versioned_models import Agent, Skill, Prompt

if TYPE_CHECKING:
    from app.services.ab_test_service import ABTestService

logger = logging.getLogger(__name__)


class TopologyLoader:
    """
    Loads agent topology from database with validation.

    Key behaviors (per CONTEXT):
    - Reload between runs only: Cache until explicit reload
    - Reject invalid, keep old: Validation failure uses cached valid topology
    - Eager skill loading: All skills loaded at topology load time
    - Prompt swap requires A/B test: Only swap prompts after A/B test validates
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        validator: Optional[TopologyValidator] = None,
        ab_test_service: Optional["ABTestService"] = None
    ):
        """
        Initialize topology loader.

        Args:
            db: Database session
            validator: Topology validator (creates default if not provided)
            ab_test_service: A/B test service for prompt swap validation (optional)
        """
        self.session_factory = session_factory
        self.validator = validator or TopologyValidator()
        self.ab_test_service = ab_test_service

        # Cached topology (per CONTEXT: reload between runs only)
        self._cached_topology: Optional[Topology] = None
        self._cached_validation: Optional[ValidationResult] = None
        self._loaded_skills: dict[str, Skill] = {}
        self._last_load_time: Optional[datetime] = None

        # Track current prompt IDs per agent for hot-swap detection
        self._current_prompt_ids: dict[str, str] = {}

    async def load(self, force_reload: bool = False) -> tuple[Topology, ValidationResult]:
        """
        Load topology from database.

        Per CONTEXT: Reload between runs only, not mid-execution.
        Use force_reload=True to reload (call between executions).

        Args:
            force_reload: Force reload from database

        Returns:
            (topology, validation_result)
        """
        if self._cached_topology and not force_reload:
            logger.debug("Using cached topology")
            return self._cached_topology, self._cached_validation

        return await self._load_from_db()

    async def _load_from_db(self) -> tuple[Topology, ValidationResult]:
        """Load topology using the given database session."""
        async with self.session_factory() as db:
            return await self._load_from_db_with_session(db)

    async def _load_from_db_with_session(self, db: AsyncSession) -> tuple[Topology, ValidationResult]:
        """Interne Ladelogik mit expliziter Session."""
        logger.info("Loading topology from database...")

        repo = TopologyRepository(db)
        agents_with_prompts = await repo.get_agents_with_prompts()

        if not agents_with_prompts:
            logger.warning("No agents found in database")
            empty_topology = Topology(
                topology_id=f"empty-{uuid4().hex[:8]}",
                name="Empty Topology",
                agents=[]
            )
            result = ValidationResult(
                is_valid=False,
                errors=["No agents in database"]
            )
            return empty_topology, result

        # Build name->id lookup for resolving dependencies
        name_to_id = {agent.name: agent.id for agent, _ in agents_with_prompts}

        # Load skills and map by capability (applicability → metadata → name fallback)
        capability_to_skills, skill_metadata_map = await self._map_skills_to_capabilities(db=db)

        # Convert to AgentNode models
        agent_nodes = []
        for agent, prompt in agents_with_prompts:
            # Resolve dependency names to IDs
            resolved_deps = []
            for dep in (agent.dependencies or []):
                if dep in name_to_id:
                    resolved_deps.append(name_to_id[dep])
                elif dep in {a.id for a, _ in agents_with_prompts}:
                    # Already an ID
                    resolved_deps.append(dep)
                else:
                    logger.warning(f"Agent {agent.name}: dependency '{dep}' not found")

            # Bind skills to agent:
            # 1. Explicit assignment via skill_metadata.target_agent_id
            # 2. All unassigned skills are available to all agents
            agent_skill_ids = []
            agent_caps = []
            for cap, sids in capability_to_skills.items():
                for sid in sids:
                    # Check if skill is explicitly assigned to a different agent
                    skill_meta = skill_metadata_map.get(sid, {})
                    target = skill_meta.get("target_agent_id") or skill_meta.get("assigned_agent")
                    if target and target != agent.id and target != agent.name:
                        continue
                    if sid not in agent_skill_ids:
                        agent_skill_ids.append(sid)
                        agent_caps.append(cap)

            node = AgentNode(
                agent_id=agent.id,
                name=agent.name,
                prompt_id=agent.prompt_id,
                capabilities=agent_caps,
                dependencies=resolved_deps,
                skill_ids=list(set(agent_skill_ids)),  # Deduplicate skill IDs
                config={},
                is_active=agent.is_active,
                input_schema=agent.io_schema.get("input") if agent.io_schema else None,
                output_schema=agent.io_schema.get("output") if agent.io_schema else None,
                consumes_artifacts=agent.io_schema.get("consumes", []) if agent.io_schema else [],
                produces_artifacts=agent.io_schema.get("produces", []) if agent.io_schema else []
            )
            agent_nodes.append(node)

            if agent_skill_ids:
                logger.debug(f"Agent {agent.name}: bound {len(agent_skill_ids)} skills")

        # Create topology
        topology = Topology(
            topology_id=f"db-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
            name="Database Topology",
            agents=agent_nodes,
            is_active=True
        )

        # Validate topology
        result = self.validator.validate(topology)

        if result.is_valid:
            # Update cache
            self._cached_topology = topology
            self._cached_validation = result
            self._last_load_time = datetime.now(timezone.utc)

            # Track current prompt IDs for hot-swap detection
            self._current_prompt_ids = {
                agent.agent_id: agent.prompt_id
                for agent in agent_nodes
                if agent.prompt_id
            }

            # Eager skill loading (per CONTEXT)
            await self._load_skills(topology, db)

            logger.info(
                f"Topology loaded: {len(agent_nodes)} agents, "
                f"{len(result.execution_waves)} waves"
            )
        else:
            # Per CONTEXT: Reject invalid, keep old
            logger.error(f"Topology validation failed: {result.errors}")
            if self._cached_topology:
                logger.warning("Using previously cached valid topology")
                topology = self._cached_topology
                # Return new result but use old topology
            else:
                logger.error("No cached topology available, returning invalid")

        return topology, result

    def _normalize_capability_for_matching(self, name: str) -> str:
        """
        Normalize capability name for robust skill-to-agent matching.

        Handles variations like:
        - "risk assessment (downtime costs)" -> "risk assessment"
        - "Cost_Analysis" -> "cost analysis"
        """
        import re
        # Lowercase and strip
        normalized = name.lower().strip()
        # Remove content in parentheses
        normalized = re.sub(r'\s*\([^)]*\)', '', normalized)
        # Replace underscores/hyphens with spaces
        normalized = normalized.replace('_', ' ').replace('-', ' ')
        # Normalize whitespace
        normalized = ' '.join(normalized.split())
        return normalized

    async def _map_skills_to_capabilities(self, db: AsyncSession) -> tuple[dict[str, list[str]], dict[str, dict]]:
        """
        Map active skills to capabilities for agent binding.

        Returns:
            Tuple of (capability_name -> [skill_ids], skill_id -> skill_metadata).

        Capability sources (priority order):
        1. skill.applicability (SoK C field — primary, set by builder)
        2. skill_metadata.affected_capability (legacy fallback)
        3. skill name derived (last resort)
        """
        capability_to_skills: dict[str, list[str]] = {}
        skill_metadata_map: dict[str, dict] = {}

        result = await db.execute(
            select(Skill).where(Skill.is_active == True)
        )
        skills = result.scalars().all()

        for skill in skills:
            mapped_caps = []
            skill_metadata_map[skill.id] = skill.skill_metadata or {}

            # Priority 1: Skill.applicability (SoK field)
            if skill.applicability:
                cap_normalized = self._normalize_capability_for_matching(skill.applicability)
                mapped_caps.append(cap_normalized)
                logger.debug(f"Skill {skill.name} mapped via applicability to '{cap_normalized}'")

            # Priority 2: affected_capability in metadata (legacy)
            if not mapped_caps and skill.skill_metadata and skill.skill_metadata.get("affected_capability"):
                affected_cap = skill.skill_metadata["affected_capability"]
                cap_normalized = self._normalize_capability_for_matching(affected_cap)
                mapped_caps.append(cap_normalized)
                logger.debug(f"Skill {skill.name} mapped via metadata to '{cap_normalized}'")

            # Priority 3: Fallback - derive from skill name
            if not mapped_caps:
                skill_name_cap = skill.name.replace("skill_", "").replace("_", " ")
                cap_from_name = self._normalize_capability_for_matching(skill_name_cap)
                if cap_from_name:
                    mapped_caps.append(cap_from_name)
                    logger.debug(f"Skill {skill.name} mapped via name to '{cap_from_name}'")

            for cap in mapped_caps:
                if cap not in capability_to_skills:
                    capability_to_skills[cap] = []
                if skill.id not in capability_to_skills[cap]:
                    capability_to_skills[cap].append(skill.id)

        if capability_to_skills:
            total_skills = sum(len(v) for v in capability_to_skills.values())
            logger.info(
                f"Mapped {total_skills} skill entries to {len(capability_to_skills)} capabilities"
            )

        return capability_to_skills, skill_metadata_map

    async def _load_skills(self, topology: Topology, db: AsyncSession) -> None:
        """
        Eagerly load all skills for topology agents.

        Per CONTEXT: All skills loaded at run start, not lazy.
        """
        skill_ids = set()
        for agent in topology.agents:
            skill_ids.update(agent.skill_ids)

        if skill_ids:
            result = await db.execute(
                select(Skill).where(Skill.id.in_(skill_ids))
            )
            skills = result.scalars().all()
            self._loaded_skills = {skill.id: skill for skill in skills}
            logger.info(f"Loaded {len(self._loaded_skills)} skills for topology")

    def get_cached_topology(self) -> Optional[Topology]:
        """Get currently cached topology."""
        return self._cached_topology

    def get_loaded_skill(self, skill_id: str) -> Optional[Skill]:
        """Get eagerly loaded skill."""
        return self._loaded_skills.get(skill_id)

    def get_all_loaded_skills(self) -> dict[str, Skill]:
        """Get all eagerly loaded skills."""
        return self._loaded_skills.copy()

    async def reload(self) -> tuple[Topology, ValidationResult]:
        """
        Force reload topology from database.

        Call this between execution runs when topology may have changed.
        """
        return await self.load(force_reload=True)

    def is_loaded(self) -> bool:
        """Check if topology is loaded."""
        return self._cached_topology is not None

    def get_execution_order(self) -> Optional[list[str]]:
        """Get cached execution order."""
        if self._cached_validation:
            return self._cached_validation.execution_order
        return None

    def get_execution_waves(self) -> Optional[list[list[str]]]:
        """Get cached execution waves."""
        if self._cached_validation:
            return self._cached_validation.execution_waves
        return None

    def get_agent_node(self, agent_id: str) -> Optional[AgentNode]:
        """Get agent node from cached topology."""
        if self._cached_topology:
            return self._cached_topology.get_agent(agent_id)
        return None

    async def swap_agent_prompt(
        self,
        agent_id: str,
        new_prompt_id: str,
        ab_test_id: Optional[str] = None
    ) -> tuple[bool, str]:
        """
        Swap an agent's prompt after A/B test validation.

        Per CONTEXT: Prompts can only be swapped after A/B test validates the new version.

        Args:
            agent_id: Agent to update
            new_prompt_id: New prompt ID to assign
            ab_test_id: A/B test ID that validated this prompt (required unless ab_test_service is None)

        Returns:
            (success, message) - True if swap succeeded, False with reason if not
        """
        async with self.session_factory() as db:
            # Verify new prompt exists
            prompt_result = await db.execute(
                select(Prompt).where(Prompt.id == new_prompt_id)
            )
            new_prompt = prompt_result.scalar_one_or_none()
            if not new_prompt:
                return False, f"Prompt {new_prompt_id} not found"

            # Verify agent exists
            agent_result = await db.execute(
                select(Agent).where(Agent.id == agent_id)
            )
            agent = agent_result.scalar_one_or_none()
            if not agent:
                return False, f"Agent {agent_id} not found"

            # Check A/B test validation (per CONTEXT: Prompt swap requires A/B test)
            if self.ab_test_service:
                if not ab_test_id:
                    return False, "A/B test ID required for prompt swap"

                # Verify A/B test completed successfully with improvement as winner
                try:
                    ab_test = await self.ab_test_service.get_test(ab_test_id)
                    if not ab_test:
                        return False, f"A/B test {ab_test_id} not found"

                    if ab_test.status != "completed":
                        return False, f"A/B test {ab_test_id} not completed (status: {ab_test.status})"

                    # is_significant == 1 means improvement won (per ABTest model)
                    if ab_test.is_significant != 1:
                        return False, f"A/B test {ab_test_id} did not validate improvement (is_significant: {ab_test.is_significant})"

                    # Verify the test was for a prompt artifact
                    if ab_test.artifact_type != "prompt":
                        return False, f"A/B test {ab_test_id} was not for a prompt (type: {ab_test.artifact_type})"

                except Exception as e:
                    logger.error(f"Failed to verify A/B test: {e}")
                    return False, f"A/B test verification failed: {str(e)}"
            else:
                logger.warning("No A/B test service configured - allowing prompt swap without validation")

            # Perform the swap
            old_prompt_id = agent.prompt_id
            await db.execute(
                update(Agent)
                .where(Agent.id == agent_id)
                .values(prompt_id=new_prompt_id)
            )
            await db.commit()

            # Update tracking
            self._current_prompt_ids[agent_id] = new_prompt_id

            logger.info(
                f"Prompt swapped for agent {agent_id}: "
                f"{old_prompt_id} -> {new_prompt_id} "
                f"(validated by A/B test {ab_test_id})"
            )

            return True, f"Prompt swapped successfully for agent {agent_id}"

    async def check_prompt_update(self, agent_id: str, new_prompt_id: str) -> bool:
        """
        Check if prompt can be updated for agent.

        Per CONTEXT: Prompt swap requires A/B test validation.
        This method just checks if prompt exists and is different.
        Actual swap happens via swap_agent_prompt() after A/B test.

        Returns:
            True if prompt exists and would be a change
        """
        async with self.session_factory() as db:
            result = await db.execute(
                select(Prompt).where(Prompt.id == new_prompt_id)
            )
            prompt = result.scalar_one_or_none()

            if not prompt:
                return False

            # Check if it's actually different from current
            current_prompt_id = self._current_prompt_ids.get(agent_id)
            return current_prompt_id != new_prompt_id


async def create_topology_loader(
    session_factory: async_sessionmaker[AsyncSession],
    ab_test_service: Optional["ABTestService"] = None
) -> "TopologyLoader":
    """Factory function to create and initialize TopologyLoader."""
    loader = TopologyLoader(session_factory, ab_test_service=ab_test_service)
    await loader.load()
    return loader
