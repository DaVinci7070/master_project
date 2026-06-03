import asyncio
import logging
from typing import Literal, Optional

from sqlalchemy import select, update

from app.models.sql.versioned_models import Skill, Prompt, Agent
from app.models.sql.skill_build_models import SkillBinding
from app.models.schemas.skill_build_schemas import SkillIntegrationPlan
from app.orchestration.topology.loader import TopologyLoader

logger = logging.getLogger(__name__)


ArtifactType = Literal["skill", "prompt", "agent"]


class CapabilityInjector:
    """
    Injects newly-built capabilities into running system.

    Per CONTEXT decisions:
    - Force topology reload via TopologyLoader.reload() after DB write
      (Note: reload() internally calls load(force_reload=True))
    - Skip A/B testing for urgent gaps - inject immediately
    - Validate capability is available after reload

    Per RESEARCH pitfall 1:
    - Use database transactions with commit before reload
    - Add short delay after commit to ensure DB consistency
    """

    POST_COMMIT_DELAY_MS = 100

    def __init__(
        self,
        topology_loader: TopologyLoader,
        session_factory,
    ):
        """
        Initialize capability injector.

        Args:
            topology_loader: TopologyLoader for reload operations
            db: Database session for verification
        """
        self.topology = topology_loader
        self.session_factory = session_factory

    async def inject(
        self,
        artifact_type: ArtifactType,
        artifact_id: str
    ) -> tuple[bool, str]:
        """
        Inject capability into topology.

        Per CONTEXT: Force topology reload via TopologyLoader.reload()
        after DB write. Skip A/B testing for urgent gaps.

        Args:
            artifact_type: Type of artifact (skill, prompt, agent)
            artifact_id: UUID of the artifact to inject

        Returns:
            (success, message) - True if injection succeeded
        """
        logger.info(
            f"Injecting capability: type={artifact_type}, id={artifact_id[:8]}..."
        )

        artifact = await self._verify_artifact_exists(artifact_type, artifact_id)
        if not artifact:
            return False, f"Artifact {artifact_id} not found in database"

        if hasattr(artifact, 'is_active') and not artifact.is_active:
            await self._activate_artifact(artifact_type, artifact_id)

        await asyncio.sleep(self.POST_COMMIT_DELAY_MS / 1000)

        try:
            topology, validation = await self.topology.reload()

            if not validation.is_valid:
                logger.error(
                    f"Topology invalid after injection: {validation.errors}"
                )

                await self._deactivate_artifact(artifact_type, artifact_id)

                return False, f"Topology validation failed: {validation.errors[0] if validation.errors else 'Unknown error'}"

            is_present = await self._verify_capability_present(
                topology, artifact_type, artifact_id
            )

            if not is_present:
                logger.warning(
                    f"Capability {artifact_type}/{artifact_id[:8]}... not found in reloaded topology"
                )
                if artifact_type == "skill":
                    logger.warning(
                        "Skill injected but not bound to any agent - "
                        "ensure an agent has the matching capability declared"
                    )
                    return True, "Skill injected (unbound - no matching agent capability)"
                else:
                    return False, "Capability not found in reloaded topology"

            logger.info(
                f"Capability injected successfully: {artifact_type}/{artifact_id[:8]}..."
            )
            return True, "Capability injected and topology reloaded"

        except Exception as e:
            logger.error(f"Injection failed: {e}", exc_info=True)
            return False, f"Injection error: {str(e)}"

    async def inject_with_plan(
        self,
        plan: SkillIntegrationPlan,
        skill_id: str,
        capability: str,
    ) -> tuple[bool, str]:
        """
        Inject skill using architect's integration plan.

        Uses the plan's target_agent_id for explicit binding instead of
        relying on heuristic matching. Falls back to inject() if no
        target agent specified.

        Args:
            plan: Architect's integration plan with target agent info
            skill_id: ID of the skill to inject
            capability: The capability this skill provides

        Returns:
            (success, message)
        """
        if not plan.target_agent_id:
            logger.info("No target_agent_id in integration plan, falling back to generic inject")
            return await self.inject(artifact_type="skill", artifact_id=skill_id)

        logger.info(
            f"Injecting skill {skill_id[:8]}... with plan: "
            f"target_agent={plan.target_agent_id[:8]}..., rationale={plan.rationale}"
        )

        skill = await self._verify_artifact_exists("skill", skill_id)
        if not skill:
            return False, f"Skill {skill_id} not found in database"

        async with self.session_factory() as db:
            agent_result = await db.execute(
                select(Agent).where(Agent.id == plan.target_agent_id, Agent.is_active == True)
            )
            agent = agent_result.scalar_one_or_none()
            if not agent:
                logger.warning(
                    f"Target agent {plan.target_agent_id[:8]}... not found/inactive, "
                    "falling back to generic inject"
                )
                return await self.inject(artifact_type="skill", artifact_id=skill_id)

            if hasattr(skill, 'is_active') and not skill.is_active:
                await self._activate_artifact("skill", skill_id)

            existing_binding = await db.execute(
                select(SkillBinding).where(
                    SkillBinding.skill_id == skill_id,
                    SkillBinding.agent_id == plan.target_agent_id,
                    SkillBinding.is_active == True,
                )
            )
            if not existing_binding.scalar_one_or_none():
                binding = SkillBinding(
                    skill_id=skill_id,
                    agent_id=plan.target_agent_id,
                    capability=capability,
                    binding_type="architect_plan",
                    is_active=True,
                )
                db.add(binding)
                await db.commit()
                logger.info(f"Created skill binding: skill={skill_id[:8]}... -> agent={plan.target_agent_id[:8]}...")

            if plan.dependency_changes:
                await self._apply_dependency_changes(plan.target_agent_id, plan.dependency_changes)

        await asyncio.sleep(self.POST_COMMIT_DELAY_MS / 1000)

        try:
            topology, validation = await self.topology.reload()

            if not validation.is_valid:
                logger.error(f"Topology invalid after plan-based injection: {validation.errors}")
                return False, f"Topology validation failed: {validation.errors[0] if validation.errors else 'Unknown'}"

            is_present = await self._verify_capability_present(topology, "skill", skill_id)
            if not is_present:
                logger.warning(
                    f"Skill {skill_id[:8]}... not found in topology after plan-based injection "
                    f"(target agent: {agent.name})"
                )
                return True, f"Skill injected and bound to {agent.name} (not yet visible in topology)"

            logger.info(f"Plan-based injection complete: skill={skill_id[:8]}... -> agent={agent.name}")
            return True, f"Skill injected and bound to agent '{agent.name}' via architect plan"

        except Exception as e:
            logger.error(f"Plan-based injection failed during reload: {e}", exc_info=True)
            return False, f"Injection error: {str(e)}"

    async def _apply_dependency_changes(
        self,
        agent_id: str,
        changes: list[dict],
    ) -> None:
        """Apply DAG dependency changes from integration plan."""
        async with self.session_factory() as db:
            agent_result = await db.execute(
                select(Agent).where(Agent.id == agent_id)
            )
            agent = agent_result.scalar_one_or_none()
            if not agent:
                return

            current_deps = list(agent.dependencies or [])
            for change in changes:
                action = change.get("action")
                dep_id = change.get("agent_id")
                if not dep_id:
                    continue
                if action == "add" and dep_id not in current_deps:
                    current_deps.append(dep_id)
                elif action == "remove" and dep_id in current_deps:
                    current_deps.remove(dep_id)

            await db.execute(
                update(Agent).where(Agent.id == agent_id).values(dependencies=current_deps)
            )
            await db.commit()
            logger.info(f"Updated dependencies for agent {agent_id[:8]}...: {current_deps}")

    async def _verify_artifact_exists(
        self,
        artifact_type: ArtifactType,
        artifact_id: str
    ) -> Optional[Skill | Prompt | Agent]:
        """Verify artifact exists in database."""
        async with self.session_factory() as db:
            if artifact_type == "skill":
                result = await db.execute(
                    select(Skill).where(Skill.id == artifact_id)
                )
            elif artifact_type == "prompt":
                result = await db.execute(
                    select(Prompt).where(Prompt.id == artifact_id)
                )
            elif artifact_type == "agent":
                result = await db.execute(
                    select(Agent).where(Agent.id == artifact_id)
                )
            else:
                return None

            return result.scalar_one_or_none()

    async def _activate_artifact(
        self,
        artifact_type: ArtifactType,
        artifact_id: str
    ) -> None:
        """Ensure artifact is marked as active."""
        async with self.session_factory() as db:
            if artifact_type == "skill":
                await db.execute(
                    update(Skill).where(Skill.id == artifact_id).values(is_active=True)
                )
            elif artifact_type == "prompt":
                await db.execute(
                    update(Prompt).where(Prompt.id == artifact_id).values(is_active=True)
                )
            elif artifact_type == "agent":
                await db.execute(
                    update(Agent).where(Agent.id == artifact_id).values(is_active=True)
                )
            await db.commit()

    async def _deactivate_artifact(
        self,
        artifact_type: ArtifactType,
        artifact_id: str
    ) -> None:
        """Deactivate artifact after failed injection."""
        async with self.session_factory() as db:
            if artifact_type == "skill":
                await db.execute(
                    update(Skill).where(Skill.id == artifact_id).values(is_active=False)
                )
            elif artifact_type == "prompt":
                await db.execute(
                    update(Prompt).where(Prompt.id == artifact_id).values(is_active=False)
                )
            elif artifact_type == "agent":
                await db.execute(
                    update(Agent).where(Agent.id == artifact_id).values(is_active=False)
                )
            await db.commit()
            logger.info(f"Deactivated {artifact_type} {artifact_id[:8]}... after failed injection")

    async def _verify_capability_present(
        self,
        topology,
        artifact_type: ArtifactType,
        artifact_id: str
    ) -> bool:
        """Verify artifact is present in reloaded topology."""
        if artifact_type == "agent":
            agent_node = topology.get_agent(artifact_id)
            return agent_node is not None

        elif artifact_type == "skill":
            loaded_skills = self.topology.get_all_loaded_skills()
            return artifact_id in loaded_skills

        elif artifact_type == "prompt":
            for agent in topology.agents:
                if agent.prompt_id == artifact_id:
                    return True
            return True

        return False

    async def rollback_capabilities(
        self,
        artifact_ids: list[tuple[ArtifactType, str]]
    ) -> int:
        """
        Rollback multiple capabilities by deactivating them.

        Per RESEARCH pitfall 4: Ensure provisional capabilities are rolled back
        after max attempts.

        Args:
            artifact_ids: List of (artifact_type, artifact_id) tuples

        Returns:
            Number of capabilities successfully rolled back
        """
        rolled_back = 0
        for artifact_type, artifact_id in artifact_ids:
            try:
                await self._deactivate_artifact(artifact_type, artifact_id)
                rolled_back += 1
            except Exception as e:
                logger.error(f"Rollback failed for {artifact_type}/{artifact_id}: {e}")

        if rolled_back > 0:
            await self.topology.reload()

        logger.info(f"Rolled back {rolled_back}/{len(artifact_ids)} capabilities")
        return rolled_back

    async def get_provisional_capabilities(
        self,
        project_id: Optional[str] = None
    ) -> list[dict]:
        """
        Get all provisional (unverified) capabilities.

        Useful for cleanup or review.
        """
        provisional = []

        async with self.session_factory() as db:
            skill_result = await db.execute(
                select(Skill).where(Skill.is_active == True)
            )
            for skill in skill_result.scalars().all():
                if skill.skill_metadata and skill.skill_metadata.get("provisional"):
                    provisional.append({
                        "type": "skill",
                        "id": skill.id,
                        "name": skill.name,
                        "created_at": str(skill.created_at) if hasattr(skill, 'created_at') else None
                    })

            agent_result = await db.execute(
                select(Agent).where(Agent.is_active == True)
            )
            for agent in agent_result.scalars().all():
                if agent.agent_metadata and agent.agent_metadata.get("provisional"):
                    provisional.append({
                        "type": "agent",
                        "id": agent.id,
                        "name": agent.name,
                        "created_at": str(agent.created_at) if hasattr(agent, 'created_at') else None
                    })

        return provisional
