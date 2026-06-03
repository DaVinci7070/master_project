import logging
import os
import re
import uuid
from typing import Optional, Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select, update

from app.models.schemas.analysis_schemas import CapabilityGap, GapType, GapSeverity
from app.models.schemas.intervention_schemas import BuildResult
from app.models.schemas.developer_team_schemas import DevelopmentTask
from app.models.schemas.skill_build_schemas import SkillTeamConfig
from app.models.sql.versioned_models import Skill, Prompt, Agent
from app.models.sql.skill_build_models import SkillBinding
from app.orchestration.intervention.retry_strategy import ApproachSelector
from app.orchestration.agents.developer_team import DeveloperTeamOrchestrator

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.skills.building.team_orchestrator import SkillTeamOrchestrator

logger = logging.getLogger(__name__)

MIN_AGENT_AFFINITY_SCORE = 0.3


class CapabilityBuilder:
    """
    Builds missing capabilities using Developer Team or Skill Team.

    Per CONTEXT decisions:
    - Developer Team can build all types: skills, prompts, and new agents
    - Skill Team provides higher quality through team-based development
    - Mark injected capabilities as "provisional" for post-execution review
    - Include previous failed attempts so teams try different approaches

    Routes to appropriate builder based on gap type and configuration.
    """

    def __init__(
        self,
        developer_team: DeveloperTeamOrchestrator,
        session_factory: async_sessionmaker[AsyncSession],
        embedding_fn: Optional[Callable[[str], Awaitable[list[float]]]] = None,
        skill_team_config: Optional[SkillTeamConfig] = None,
    ):
        self.developer_team = developer_team
        self.session_factory = session_factory
        self._get_embedding = embedding_fn
        self._skill_team_config = skill_team_config or SkillTeamConfig()
        self._skill_team: Optional["SkillTeamOrchestrator"] = None

    async def build_for_gap(
        self,
        gap: CapabilityGap,
        challenge_text: str,
        attempt_number: int,
        previous_failures: list[str]
    ) -> BuildResult:
        """
        Build capability to fill a gap.

        Per CONTEXT:
        - Build highest-severity gaps first (Critical -> Important -> Minor)
        - Vary approach across retry attempts

        Args:
            gap: The capability gap to fill
            challenge_text: Original challenge text for context
            attempt_number: Current attempt number (1-5)
            previous_failures: List of failure reasons from prior attempts

        Returns:
            BuildResult with success status, artifact_id, or failure reason
        """
        approach = ApproachSelector.select(attempt_number)

        logger.info(
            f"Building capability: gap_type={gap.gap_type.value}, "
            f"severity={gap.severity.value}, "
            f"attempt={attempt_number}, approach={approach.name}"
        )

        if gap.gap_type == GapType.MISSING_SKILL:
            return await self._build_skill(
                gap, challenge_text, approach.name, approach.constraints, previous_failures
            )
        elif gap.gap_type == GapType.MISSING_PLANNING_SKILL:
            return await self._build_prompt(
                gap, challenge_text, approach.name, approach.constraints, previous_failures
            )
        elif gap.gap_type == GapType.WEAK_PROMPT:
            return await self._build_prompt(
                gap, challenge_text, approach.name, approach.constraints, previous_failures
            )
        elif gap.gap_type == GapType.MISSING_AGENT:
            return await self._build_agent(
                gap, challenge_text, approach.name, approach.constraints, previous_failures
            )
        elif gap.gap_type == GapType.TOPOLOGY_ISSUE:
            return await self._build_agent(
                gap, challenge_text, approach.name, approach.constraints, previous_failures
            )
        elif gap.gap_type == GapType.SCHEMA_MISMATCH:
            skill_result = await self._build_skill(
                gap, challenge_text, approach.name, approach.constraints, previous_failures
            )
            if skill_result.success:
                return skill_result
            logger.warning(
                f"Skill build for SCHEMA_MISMATCH failed, falling back to agent build: "
                f"{skill_result.failure_reason}"
            )
            return await self._build_agent(
                gap, challenge_text, approach.name, approach.constraints, previous_failures
            )
        else:
            return BuildResult(
                success=False,
                artifact_id=None,
                artifact_type="skill",
                failure_reason=f"Unknown gap type: {gap.gap_type.value}",
                approach_used=approach.name,
                duration_seconds=0.0
            )

    def get_skill_team(self) -> "SkillTeamOrchestrator":
        """Get or create the Skill Team Orchestrator."""
        if self._skill_team is None:
            from app.skills.building.team_orchestrator import SkillTeamOrchestrator
            self._skill_team = SkillTeamOrchestrator(
                session_factory=self.session_factory,
                config=self._skill_team_config,
            )
        return self._skill_team

    _DB_CREDENTIAL_PATTERN = re.compile(
        r'Host:\s*([^\s,]+)'
        r'[\s,]+'
        r'Port:\s*(\d+)'
        r'[\s,]+'
        r'User:\s*([^\s,]+)'
        r'[\s,]+'
        r'(?:Passwort|Password):\s*([^\s,]+)'
        r'[\s,]+'
        r'DB:\s*([^\s,\)\.\]]+)',
        re.IGNORECASE,
    )

    @staticmethod
    def _extract_test_context(
        challenge_text: str,
        capability: str,
    ) -> tuple[dict | None, dict[str, bytes] | None]:
        """Leitet Test-Input und Dateien aus dem Challenge-Kontext ab."""
        test_input = None
        input_files = None

        path_match = re.search(r'Storage Path: (.+)', challenge_text)
        if path_match:
            file_path = path_match.group(1).strip()
            if os.path.isdir(file_path):
                dir_name = os.path.basename(file_path.rstrip("/"))
                test_input = {"file_path": f"/workspace/{dir_name}/"}
                input_files = {}
                for fname in os.listdir(file_path):
                    fpath = os.path.join(file_path, fname)
                    if os.path.isfile(fpath):
                        with open(fpath, "rb") as f:
                            input_files[f"{dir_name}/{fname}"] = f.read()
                logger.info(f"Test-Verzeichnis extrahiert: {dir_name}/ ({len(input_files)} Dateien)")
            elif os.path.isfile(file_path):
                basename = os.path.basename(file_path)
                test_input = {"file_path": f"/workspace/{basename}"}
                with open(file_path, "rb") as f:
                    input_files = {basename: f.read()}
                logger.info(f"Test-Datei aus Challenge extrahiert: {basename}")

        db_match = CapabilityBuilder._DB_CREDENTIAL_PATTERN.search(challenge_text)
        if db_match:
            host, port, user, password, dbname = db_match.groups()
            db_url = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
            if test_input is None:
                test_input = {}
            test_input["database_url"] = db_url
            logger.info(f"DB-Credentials aus Challenge extrahiert: {host}:{port}/{dbname}")

        return test_input, input_files

    async def _build_skill(
        self,
        gap: CapabilityGap,
        challenge_text: str,
        approach: str,
        constraints: list[str],
        previous_failures: list[str]
    ) -> BuildResult:
        """Build a new skill using the Skill Team Orchestrator (Self-Healing v2)."""
        import time
        start_time = time.time()

        skill_name = f"skill_{gap.affected_capability.lower().replace(' ', '_').replace('-', '_')}"
        existing = await self._find_existing_skill(skill_name)
        if existing and existing.is_active:
            validation_passed = await self._validate_existing_skill(existing)
            if validation_passed:
                logger.info(
                    f"Warm-Skill '{existing.name}' validiert — wiederverwenden"
                )
                bound_agent_id = await self._expand_agent_capabilities(
                    skill_id=existing.id,
                    affected_capability=gap.affected_capability,
                )
                return BuildResult(
                    success=True,
                    artifact_id=existing.id,
                    artifact_type="skill",
                    failure_reason=None,
                    approach_used="reuse_existing",
                    duration_seconds=time.time() - start_time,
                    bound_to_agent_id=bound_agent_id,
                )
            else:
                logger.warning(
                    f"Warm-Skill '{existing.name}' Validation fehlgeschlagen — "
                    f"deaktiviere und baue neu"
                )
                await self.deactivate_provisional("skill", existing.id)

        logger.info(f"Using Skill Team for capability: {gap.affected_capability}")
        return await self._build_skill_with_team(gap, start_time, challenge_text)

    async def _build_skill_with_team(
        self,
        gap: CapabilityGap,
        start_time: float,
        challenge_text: str = "",
    ) -> BuildResult:
        """
        Build a skill using the Skill Team Orchestrator.

        This provides higher quality through team-based development:
        - Research phase finds packages and examples
        - Architect designs the API and tests
        - Implementer writes the code
        - Reviewer checks quality and security
        """
        import time

        try:
            skill_team = self.get_skill_team()

            test_input, input_files = self._extract_test_context(
                challenge_text, gap.affected_capability
            )

            result = await skill_team.develop_skill(
                capability=gap.affected_capability,
                test_input=test_input,
                input_files=input_files,
                hints={
                    "description": gap.description,
                    "challenge_context": challenge_text[:500] if challenge_text else "",
                },
            )

            duration = time.time() - start_time

            if result.success:
                logger.info(
                    f"Skill Team built skill: {result.skill_name}, "
                    f"duration={duration:.1f}s"
                )

                expanded_agent_id = await self._expand_agent_capabilities(
                    skill_id=result.skill_id,
                    affected_capability=gap.affected_capability
                )

                return BuildResult(
                    success=True,
                    artifact_id=result.skill_id,
                    artifact_type="skill",
                    failure_reason=None,
                    approach_used="skill_team",
                    duration_seconds=duration,
                    integration_plan=result.integration_plan,
                    bound_to_agent_id=expanded_agent_id,
                )
            else:
                logger.warning(
                    f"Skill Team failed: phase={result.failure_phase}, "
                    f"reason={result.failure_reason}"
                )
                return BuildResult(
                    success=False,
                    artifact_id=None,
                    artifact_type="skill",
                    failure_reason=result.failure_reason,
                    approach_used="skill_team",
                    duration_seconds=duration,
                )

        except Exception as e:
            logger.error(f"Skill Team exception: {e}", exc_info=True)
            return BuildResult(
                success=False,
                artifact_id=None,
                artifact_type="skill",
                failure_reason=str(e),
                approach_used="skill_team",
                duration_seconds=time.time() - start_time,
            )

    async def _build_prompt(
        self,
        gap: CapabilityGap,
        challenge_text: str,
        approach: str,
        constraints: list[str],
        previous_failures: list[str]
    ) -> BuildResult:
        """
        Build or improve a prompt.

        For weak prompts, this creates a new version rather than
        modifying the existing one (versioned approach).
        """
        import time
        start_time = time.time()

        prompt_name = f"prompt_{gap.affected_capability.replace(' ', '_').lower()}"

        task_description = self._build_task_description(
            gap=gap,
            challenge_text=challenge_text,
            approach=approach,
            previous_failures=previous_failures,
            artifact_type="prompt"
        )

        task = DevelopmentTask(
            task_id=str(uuid.uuid4()),
            description=task_description,
            files_involved=[f"prompts/generated/{prompt_name}.txt"],
            context_files=[],
            constraints=[
                f"Build using {approach} approach",
                "Follow prompt engineering best practices",
                "Include clear instructions and examples",
                *constraints
            ]
        )

        try:
            result = await self.developer_team.execute_complex_task(task)

            if result.success and result.results:
                spawn_result = result.results[0]
                prompt_content = spawn_result.generated_code or ""

                prompt = Prompt(
                    id=str(uuid.uuid4()),
                    name=prompt_name,
                    content=prompt_content,
                    prompt_metadata={
                        "built_by": "intervention_orchestrator",
                        "gap_type": gap.gap_type.value,
                        "approach": approach,
                        "provisional": True,
                        "affected_capability": gap.affected_capability,
                    },
                    is_active=True
                )
                async with self.session_factory() as db:
                    db.add(prompt)
                    await db.commit()
                    await db.refresh(prompt)

                duration = time.time() - start_time
                logger.info(f"Built prompt: id={prompt.id[:8]}..., name={prompt_name}")

                return BuildResult(
                    success=True,
                    artifact_id=prompt.id,
                    artifact_type="prompt",
                    failure_reason=None,
                    approach_used=approach,
                    duration_seconds=duration
                )
            else:
                failure = result.error_summary or "Unknown prompt build failure"
                return BuildResult(
                    success=False,
                    artifact_id=None,
                    artifact_type="prompt",
                    failure_reason=failure,
                    approach_used=approach,
                    duration_seconds=time.time() - start_time
                )

        except Exception as e:
            logger.error(f"Prompt build exception: {e}", exc_info=True)
            return BuildResult(
                success=False,
                artifact_id=None,
                artifact_type="prompt",
                failure_reason=str(e),
                approach_used=approach,
                duration_seconds=time.time() - start_time
            )

    async def _build_agent(
        self,
        gap: CapabilityGap,
        challenge_text: str,
        approach: str,
        constraints: list[str],
        previous_failures: list[str]
    ) -> BuildResult:
        """
        Build a new agent for missing agent or topology gaps.

        Creates agent definition with prompt and registers in database.
        """
        import time
        start_time = time.time()

        agent_name = f"agent_{gap.affected_capability.replace(' ', '_').lower()}"

        task_description = self._build_task_description(
            gap=gap,
            challenge_text=challenge_text,
            approach=approach,
            previous_failures=previous_failures,
            artifact_type="agent"
        )

        task = DevelopmentTask(
            task_id=str(uuid.uuid4()),
            description=task_description,
            files_involved=[
                f"agents/generated/{agent_name}_config.yaml",
                f"agents/generated/{agent_name}_prompt.txt"
            ],
            context_files=[],
            constraints=[
                f"Build using {approach} approach",
                "Define clear capabilities and dependencies",
                "Include IO schema for artifact validation",
                *constraints
            ]
        )

        try:
            result = await self.developer_team.execute_complex_task(task)

            if result.success and result.results:
                prompt_result = None
                agent_config = None

                async with self.session_factory() as db:
                    for spawn_result in result.results:
                        if spawn_result.file_path.endswith("_prompt.txt"):
                            prompt_content = spawn_result.generated_code or ""
                            prompt = Prompt(
                                id=str(uuid.uuid4()),
                                name=f"{agent_name}_prompt",
                                content=prompt_content,
                                prompt_metadata={
                                    "built_by": "intervention_orchestrator",
                                    "for_agent": agent_name,
                                    "provisional": True,
                                    "affected_capability": gap.affected_capability,
                                },
                                is_active=True
                            )
                            db.add(prompt)
                            await db.flush()
                            prompt_result = prompt
                        elif spawn_result.file_path.endswith("_config.yaml"):
                            agent_config = spawn_result.generated_code

                    if prompt_result and agent_config:
                        agent = Agent(
                            id=str(uuid.uuid4()),
                            name=agent_name,
                            prompt_id=prompt_result.id,
                            dependencies=[],
                            io_schema={
                                "input": {"type": "object"},
                                "output": {"type": "object"}
                            },
                            source="system_generated",
                            agent_metadata={
                                "built_by": "intervention_orchestrator",
                                "gap_type": gap.gap_type.value,
                                "approach": approach,
                                "provisional": True,
                                "config": agent_config,
                                "capabilities": [gap.affected_capability],
                            },
                            is_active=True
                        )
                        db.add(agent)
                        await db.commit()
                        await db.refresh(agent)

                        from app.orchestration.topology.service import TopologyService
                        topology_service = TopologyService(db)
                        await topology_service.log_agent_created(
                            agent=agent,
                            source="system",
                            triggered_by=f"gap:{gap.gap_type.value}",
                            details={
                                "gap_severity": gap.severity.value,
                                "affected_capability": gap.affected_capability,
                                "approach": approach,
                            }
                        )
                        await db.commit()

                    duration = time.time() - start_time
                    logger.info(f"Built agent: id={agent.id[:8]}..., name={agent_name}")

                    return BuildResult(
                        success=True,
                        artifact_id=agent.id,
                        artifact_type="agent",
                        failure_reason=None,
                        approach_used=approach,
                        duration_seconds=duration
                    )

            failure = result.error_summary or "Failed to generate agent components"
            return BuildResult(
                success=False,
                artifact_id=None,
                artifact_type="agent",
                failure_reason=failure,
                approach_used=approach,
                duration_seconds=time.time() - start_time
            )

        except Exception as e:
            logger.error(f"Agent build exception: {e}", exc_info=True)
            return BuildResult(
                success=False,
                artifact_id=None,
                artifact_type="agent",
                failure_reason=str(e),
                approach_used=approach,
                duration_seconds=time.time() - start_time
            )

    async def _find_existing_skill(self, name: str) -> Optional[Skill]:
        """Find existing skill by name for deduplication."""
        async with self.session_factory() as db:
            result = await db.execute(
                select(Skill).where(Skill.name == name)
            )
            return result.scalar_one_or_none()

    async def _validate_existing_skill(self, skill: Skill) -> bool:
        """Smoke-Test ob ein existierender Skill noch funktioniert (Imports + execute callable)."""
        try:
            metadata = skill.skill_metadata or {}
            pip_reqs = metadata.get("pip_requirements", [])
            system_pkgs = metadata.get("system_packages", [])

            test_code = f"""{skill.code}

if __name__ == "__main__":
    import inspect
    if not callable(execute):
        exit(1)
    sig = inspect.signature(execute)
    print(f"OK: execute{{sig}}")
    exit(0)
"""
            from app.skills.testing.docker_sandbox import DynamicSandboxService
            sandbox = DynamicSandboxService()
            result = await sandbox.execute(
                code=test_code,
                pip_requirements=pip_reqs,
                system_packages=system_pkgs,
            )
            return result.success
        except Exception as e:
            logger.warning(f"Skill validation error: {e}")
            return False

    def _normalize_capability(self, name: str) -> str:
        """Normalize capability name for matching."""
        normalized = name.lower().strip()
        normalized = re.sub(r'\s*\([^)]*\)', '', normalized)
        normalized = normalized.replace('_', ' ').replace('-', ' ')
        return ' '.join(normalized.split())

    async def _get_agent_capabilities(self, agent) -> list[str]:
        """Derive agent capabilities from assigned skills + agent_metadata."""
        from sqlalchemy import select
        from app.models.sql.versioned_models import Skill

        async with self.session_factory() as db:
            skills = (await db.execute(
                select(Skill).where(Skill.is_active == True)
            )).scalars().all()

        caps = []
        agent_meta = getattr(agent, "agent_metadata", None) or {}
        caps.extend(agent_meta.get("capabilities", []))

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

    async def _find_best_agent_for_capability(
        self,
        affected_capability: str
    ) -> tuple[Optional[Agent], float]:
        """
        Find the agent whose capabilities best match the new capability.

        Uses keyword overlap scoring (no embeddings needed for basic matching).
        Returns (agent, score) tuple.
        """
        async with self.session_factory() as db:
            result = await db.execute(
                select(Agent).where(Agent.is_active == True)
            )
            agents = result.scalars().all()

        if not agents:
            return None, 0.0

        cap_normalized = self._normalize_capability(affected_capability)
        cap_words = set(cap_normalized.split())

        best_agent = None
        best_score = 0.0

        for agent in agents:
            agent_caps = await self._get_agent_capabilities(agent)
            if not agent_caps:
                continue

            agent_score = 0.0
            for agent_cap in agent_caps:
                agent_cap_normalized = self._normalize_capability(agent_cap)
                agent_words = set(agent_cap_normalized.split())

                if cap_words and agent_words:
                    overlap = len(cap_words & agent_words)
                    union = len(cap_words | agent_words)
                    similarity = overlap / union if union > 0 else 0

                    if cap_normalized in agent_cap_normalized or agent_cap_normalized in cap_normalized:
                        similarity = max(similarity, 0.7)

                    agent_score = max(agent_score, similarity)

            agent_name_words = set(self._normalize_capability(agent.name).split())
            name_overlap = len(cap_words & agent_name_words)
            if name_overlap > 0:
                agent_score = max(agent_score, 0.4 + (name_overlap * 0.1))

            if agent_score > best_score:
                best_score = agent_score
                best_agent = agent

        logger.debug(
            f"Best agent for '{affected_capability}': "
            f"{best_agent.name if best_agent else 'None'} (score={best_score:.2f})"
        )

        return best_agent, best_score

    async def _expand_agent_capabilities(
        self,
        skill_id: str,
        affected_capability: str
    ) -> Optional[str]:
        """
        Expand a suitable agent's capabilities to include the new capability.

        This ensures the skill gets bound to an agent during topology reload.
        If no suitable agent exists (Option 1 fails), creates a new specialist agent (Option 4).

        Args:
            skill_id: ID of the built skill
            affected_capability: The capability the skill provides

        Returns:
            Agent ID if expanded or created, None only on error
        """
        best_agent, score = await self._find_best_agent_for_capability(affected_capability)

        if not best_agent or score < MIN_AGENT_AFFINITY_SCORE:
            logger.info(
                f"No suitable agent for capability '{affected_capability}' "
                f"(best score: {score:.2f}) - creating new specialist agent (Option 4)"
            )
            return await self._create_specialist_agent(skill_id, affected_capability)

        current_caps = await self._get_agent_capabilities(best_agent)
        cap_normalized = self._normalize_capability(affected_capability)

        for existing_cap in current_caps:
            if self._normalize_capability(existing_cap) == cap_normalized:
                logger.info(
                    f"Agent '{best_agent.name}' already has capability '{affected_capability}'"
                )
                await self._bind_skill_to_agent(
                    skill_id=skill_id,
                    agent_id=best_agent.id,
                    capability=affected_capability,
                    binding_type="auto"
                )
                return best_agent.id

        async with self.session_factory() as db:
            new_caps = current_caps + [affected_capability]
            result = await db.execute(
                select(Agent).where(Agent.id == best_agent.id)
            )
            agent = result.scalar_one()
            current_meta = agent.agent_metadata or {}
            current_meta["capabilities"] = new_caps
            await db.execute(
                update(Agent)
                .where(Agent.id == best_agent.id)
                .values(agent_metadata=current_meta)
            )
            await db.commit()

        await self._bind_skill_to_agent(
            skill_id=skill_id,
            agent_id=best_agent.id,
            capability=affected_capability,
            binding_type="auto"
        )

        logger.info(
            f"EXPANDED agent '{best_agent.name}' with capability '{affected_capability}' "
            f"(affinity score: {score:.2f}, skill: {skill_id[:8]}...)"
        )

        return best_agent.id

    async def _bind_skill_to_agent(
        self,
        skill_id: str,
        agent_id: str,
        capability: str,
        binding_type: str = "auto"
    ) -> Optional[str]:
        """
        Create an explicit SkillBinding record linking skill to agent.

        This solves the "orphaned skills" problem by ensuring every skill
        has a clear binding to an agent that can execute it.

        Args:
            skill_id: ID of the skill to bind
            agent_id: ID of the agent to bind to
            capability: The capability this binding provides
            binding_type: Type of binding (auto, manual, provisional)

        Returns:
            SkillBinding ID if created, None if already exists or error
        """
        try:
            async with self.session_factory() as db:
                existing = await db.execute(
                    select(SkillBinding).where(
                        SkillBinding.skill_id == skill_id,
                        SkillBinding.agent_id == agent_id,
                        SkillBinding.is_active == True
                    )
                )
                if existing.scalar_one_or_none():
                    logger.debug(f"Skill binding already exists: skill={skill_id[:8]}, agent={agent_id[:8]}")
                    return None

                binding = SkillBinding(
                    skill_id=skill_id,
                    agent_id=agent_id,
                    capability=capability,
                    binding_type=binding_type,
                    priority=0,
                    is_active=True
                )
                db.add(binding)
                await db.flush()

                logger.info(
                    f"Created skill binding: skill={skill_id[:8]}..., "
                    f"agent={agent_id[:8]}..., capability='{capability}'"
                )

                await db.commit()
                return binding.id

        except Exception as e:
            logger.error(f"Failed to create skill binding: {e}")
            return None

    async def _create_specialist_agent(
        self,
        skill_id: str,
        affected_capability: str
    ) -> Optional[str]:
        """
        Create a new specialist agent for a capability when no suitable agent exists.

        Option 4: Full autonomy - system creates new agents as needed.

        Args:
            skill_id: ID of the skill that triggered agent creation
            affected_capability: The capability this agent will provide

        Returns:
            New agent ID, or None on failure
        """
        try:
            agent_name = affected_capability.replace(" ", "_").lower()
            agent_name = f"specialist_{agent_name}"

            async with self.session_factory() as db:
                existing = await db.execute(
                    select(Agent).where(Agent.name == agent_name)
                )
                if existing.scalar_one_or_none():
                    logger.info(f"Specialist agent '{agent_name}' already exists")
                    existing_agent = (await db.execute(
                        select(Agent).where(Agent.name == agent_name)
                    )).scalar_one()
                    return existing_agent.id

                prompt_content = f"""You are a specialist agent for: {affected_capability}

Your role:
- Execute tasks related to {affected_capability}
- Process inputs and produce structured outputs
- Report any issues or limitations clearly

When processing a task:
1. Analyze the input requirements
2. Apply your specialized knowledge for {affected_capability}
3. Return results in the expected format
4. Include confidence levels when appropriate

Always be precise and thorough in your {affected_capability} work."""

                prompt = Prompt(
                    id=str(uuid.uuid4()),
                    name=f"{agent_name}_prompt",
                    content=prompt_content,
                    prompt_metadata={
                        "built_by": "capability_builder",
                        "for_capability": affected_capability,
                        "provisional": True,
                        "auto_generated": True
                    },
                    is_active=True
                )
                db.add(prompt)
                await db.flush()

                data_keywords = ("sql", "database", "query", "csv", "etl", "data", "pipeline", "batch", "aggregate", "schema")
                if any(kw in affected_capability.lower() for kw in data_keywords):
                    max_tool_calls = 30
                else:
                    max_tool_calls = 15

                agent = Agent(
                    id=str(uuid.uuid4()),
                    name=agent_name,
                    prompt_id=prompt.id,
                    dependencies=[],
                    io_schema={
                        "input": {"type": "object", "description": f"Input for {affected_capability}"},
                        "output": {"type": "object", "description": f"Output from {affected_capability}"}
                    },
                    source="system_generated",
                    agent_metadata={
                        "built_by": "capability_builder",
                        "source_skill_id": skill_id,
                        "provisional": True,
                        "auto_generated": True,
                        "created_for_capability": affected_capability,
                        "max_tool_calls": max_tool_calls,
                        "capabilities": [affected_capability],
                    },
                    is_active=True
                )
                db.add(agent)
                await db.commit()
                await db.refresh(agent)

                try:
                    from app.orchestration.topology.service import TopologyService
                    topology_service = TopologyService(db)
                    await topology_service.log_agent_created(
                        agent=agent,
                        source="system",
                        triggered_by=f"skill:{skill_id[:8]}",
                        details={
                            "reason": "no_suitable_agent_for_capability",
                            "affected_capability": affected_capability,
                            "auto_generated": True
                        }
                    )
                    await db.commit()
                except Exception as log_err:
                    logger.warning(f"Failed to log agent creation: {log_err}")

            await self._bind_skill_to_agent(
                skill_id=skill_id,
                agent_id=agent.id,
                capability=affected_capability,
                binding_type="auto"
            )

            logger.info(
                f"CREATED specialist agent '{agent_name}' for capability '{affected_capability}' "
                f"(id: {agent.id[:8]}..., skill: {skill_id[:8]}...)"
            )

            return agent.id

        except Exception as e:
            logger.error(f"Failed to create specialist agent: {e}", exc_info=True)
            return None

    def _build_task_description(
        self,
        gap: CapabilityGap,
        challenge_text: str,
        approach: str,
        previous_failures: list[str],
        artifact_type: str
    ) -> str:
        """Build comprehensive task description for Developer Team."""
        desc = f"""Build a Python {artifact_type} to provide capability: {gap.affected_capability}

**Gap Context:**
Type: {gap.gap_type.value}
Severity: {gap.severity.value}
Description: {gap.description}

**Challenge Requiring This:**
{challenge_text[:500]}{"..." if len(challenge_text) > 500 else ""}

**Build Approach:** {approach}

"""
        if previous_failures:
            desc += "**Previous Failures (try different approach):**\n"
            for i, failure in enumerate(previous_failures, 1):
                desc += f"{i}. {failure}\n"

        return desc

    async def deactivate_provisional(self, artifact_type: str, artifact_id: str) -> bool:
        """
        Deactivate a provisional capability after max attempts.

        Per RESEARCH pitfall 4: Provisional capabilities not rolled back.
        """
        try:
            async with self.session_factory() as db:
                if artifact_type == "skill":
                    from sqlalchemy import update
                    await db.execute(
                        update(Skill)
                        .where(Skill.id == artifact_id)
                        .values(is_active=False)
                    )
                elif artifact_type == "prompt":
                    await db.execute(
                        update(Prompt)
                        .where(Prompt.id == artifact_id)
                        .values(is_active=False)
                    )
                elif artifact_type == "agent":
                    await db.execute(
                        update(Agent)
                        .where(Agent.id == artifact_id)
                        .values(is_active=False)
                    )
                await db.commit()
            logger.info(f"Deactivated provisional {artifact_type}: {artifact_id[:8]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to deactivate {artifact_type} {artifact_id}: {e}")
            return False
