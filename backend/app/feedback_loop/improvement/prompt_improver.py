"""
Agent Prompt Improver for weak_prompt gap resolution.

Instead of creating standalone prompts that never get used,
this service improves an existing agent's prompt to better
handle the required capability.

Key insight: A "weak_prompt" gap means an agent EXISTS but its
prompt isn't good enough. The fix is to IMPROVE that agent's prompt,
not create a new unattached prompt file.
"""
import logging
import re
import time
import uuid
from typing import Optional, Callable, Awaitable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.sql.versioned_models import Agent, Prompt
from app.models.schemas.intervention_schemas import BuildResult

logger = logging.getLogger(__name__)

# Prompt for improving agent prompts
PROMPT_IMPROVEMENT_TEMPLATE = """You are an expert prompt engineer. Your task is to improve an agent's prompt to better handle a specific capability.

## Current Agent Prompt
```
{current_prompt}
```

## Capability to Improve
{affected_capability}

## Gap Description
{gap_description}

## Challenge Context
{challenge_context}

## Instructions
Improve the agent's prompt to better handle "{affected_capability}". The improved prompt should:

1. Retain all existing capabilities and instructions
2. Add specific guidance for {affected_capability}
3. Include relevant examples or templates if helpful
4. Maintain the same overall structure and tone
5. Be clear and actionable

Output ONLY the improved prompt text, no explanations or markdown code blocks."""


class AgentPromptImprover:
    """
    Service to improve agent prompts for weak_prompt gaps.

    Instead of creating standalone prompts, this service:
    1. Finds the agent best suited for the capability
    2. Loads their current prompt
    3. Generates an improved version via LLM
    4. Creates a new prompt version (preserving history)
    5. Updates the agent to use the new prompt
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm_fn: Optional[Callable[[list[dict]], Awaitable[str]]] = None
    ):
        """
        Initialize prompt improver.

        Args:
            db: Database session
            llm_fn: Function to call LLM (messages -> response text)
        """
        self.session_factory = session_factory
        self._call_llm = llm_fn

    async def improve(
        self,
        affected_capability: str,
        gap_description: str,
        challenge_context: str
    ) -> BuildResult:
        """
        Improve an agent's prompt to better handle a capability.

        Args:
            affected_capability: The capability that needs improvement
            gap_description: Description of the gap
            challenge_context: Context from the challenge

        Returns:
            BuildResult with success status and artifact info
        """
        start_time = time.time()

        try:
            # 1. Find the best agent for this capability
            agent = await self._find_agent_for_capability(affected_capability)

            if not agent:
                logger.warning(
                    f"No agent found for capability '{affected_capability}', "
                    "falling back to creating new prompt"
                )
                return await self._create_standalone_prompt(
                    affected_capability, gap_description, challenge_context, start_time
                )

            # 2. Load current prompt
            current_prompt = await self._get_agent_prompt(agent)

            if not current_prompt:
                logger.warning(
                    f"Agent '{agent.name}' has no prompt, creating new one"
                )
                return await self._create_prompt_for_agent(
                    agent, affected_capability, gap_description, challenge_context, start_time
                )

            # 3. Generate improved prompt via LLM
            improved_content = await self._generate_improved_prompt(
                current_prompt=current_prompt.content,
                affected_capability=affected_capability,
                gap_description=gap_description,
                challenge_context=challenge_context
            )

            if not improved_content:
                return BuildResult(
                    success=False,
                    artifact_id=None,
                    artifact_type="prompt",
                    failure_reason="LLM failed to generate improved prompt",
                    approach_used="prompt_improvement",
                    duration_seconds=time.time() - start_time
                )

            # 4. Create new prompt version
            new_prompt = Prompt(
                id=str(uuid.uuid4()),
                parent_id=current_prompt.id,  # Link to previous version
                name=current_prompt.name,
                content=improved_content,
                prompt_metadata={
                    **(current_prompt.prompt_metadata or {}),
                    "improved_by": "agent_prompt_improver",
                    "affected_capability": affected_capability,
                    "gap_description": gap_description[:200],
                    "previous_version_id": current_prompt.id,
                    "improvement_timestamp": time.time(),
                },
                is_active=True
            )

            async with self.session_factory() as db:
                db.add(new_prompt)

                # 5. Deactivate old prompt version
                await db.execute(
                    update(Prompt)
                    .where(Prompt.id == current_prompt.id)
                    .values(is_active=False)
                )

                # 6. Update agent to use new prompt
                await db.execute(
                    update(Agent)
                    .where(Agent.id == agent.id)
                    .values(prompt_id=new_prompt.id)
                )

                await db.commit()
                await db.refresh(new_prompt)

            # 7. Log the change
            await self._log_prompt_improvement(
                agent=agent,
                old_prompt_id=current_prompt.id,
                new_prompt_id=new_prompt.id,
                affected_capability=affected_capability
            )

            duration = time.time() - start_time
            logger.info(
                f"Improved prompt for agent '{agent.name}': "
                f"capability='{affected_capability}', "
                f"old_prompt={current_prompt.id[:8]}..., "
                f"new_prompt={new_prompt.id[:8]}..., "
                f"duration={duration:.1f}s"
            )

            return BuildResult(
                success=True,
                artifact_id=new_prompt.id,
                artifact_type="prompt",
                failure_reason=None,
                approach_used="prompt_improvement",
                duration_seconds=duration,
                bound_to_agent_id=agent.id
            )

        except Exception as e:
            logger.error(f"Prompt improvement failed: {e}", exc_info=True)
            return BuildResult(
                success=False,
                artifact_id=None,
                artifact_type="prompt",
                failure_reason=str(e),
                approach_used="prompt_improvement",
                duration_seconds=time.time() - start_time
            )

    def _normalize_capability(self, name: str) -> str:
        """Normalize capability name for matching."""
        normalized = name.lower().strip()
        normalized = re.sub(r'\s*\([^)]*\)', '', normalized)
        normalized = normalized.replace('_', ' ').replace('-', ' ')
        return ' '.join(normalized.split())

    async def _get_agent_capabilities(self, agent, db: AsyncSession) -> list[str]:
        """Derive agent capabilities from assigned skills' applicability fields."""
        from app.models.sql.versioned_models import Skill
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

    async def _find_agent_for_capability(
        self,
        affected_capability: str
    ) -> Optional[Agent]:
        """
        Find the agent whose capabilities best match the affected capability.

        Uses word overlap scoring to find the best match.
        """
        async with self.session_factory() as db:
            result = await db.execute(
                select(Agent).where(Agent.is_active == True)
            )
            agents = result.scalars().all()

            if not agents:
                return None

            cap_normalized = self._normalize_capability(affected_capability)
            cap_words = set(cap_normalized.split())

            best_agent = None
            best_score = 0.0

            for agent in agents:
                agent_caps = await self._get_agent_capabilities(agent, db)

                for agent_cap in agent_caps:
                    agent_cap_normalized = self._normalize_capability(agent_cap)
                    agent_words = set(agent_cap_normalized.split())

                    # Calculate word overlap
                    if cap_words and agent_words:
                        overlap = len(cap_words & agent_words)
                        union = len(cap_words | agent_words)
                        score = overlap / union if union > 0 else 0

                        # Boost for containment
                        if cap_normalized in agent_cap_normalized or agent_cap_normalized in cap_normalized:
                            score = max(score, 0.7)

                        if score > best_score:
                            best_score = score
                            best_agent = agent

                # Also check agent name
                agent_name_words = set(self._normalize_capability(agent.name).split())
                name_overlap = len(cap_words & agent_name_words)
                if name_overlap > 0:
                    name_score = 0.3 + (name_overlap * 0.1)
                    if name_score > best_score:
                        best_score = name_score
                        best_agent = agent

            if best_agent:
                logger.debug(
                    f"Found agent '{best_agent.name}' for capability '{affected_capability}' "
                    f"(score={best_score:.2f})"
                )

            return best_agent if best_score >= 0.2 else None

    async def _get_agent_prompt(self, agent: Agent) -> Optional[Prompt]:
        """Get the agent's current prompt."""
        if not agent.prompt_id:
            return None

        async with self.session_factory() as db:
            result = await db.execute(
                select(Prompt).where(Prompt.id == agent.prompt_id)
            )
            return result.scalar_one_or_none()

    async def _generate_improved_prompt(
        self,
        current_prompt: str,
        affected_capability: str,
        gap_description: str,
        challenge_context: str
    ) -> Optional[str]:
        """Generate improved prompt content via LLM."""
        if not self._call_llm:
            logger.warning("No LLM function configured, cannot improve prompt")
            return None

        prompt_text = PROMPT_IMPROVEMENT_TEMPLATE.format(
            current_prompt=current_prompt,
            affected_capability=affected_capability,
            gap_description=gap_description,
            challenge_context=challenge_context[:1000]
        )

        messages = [
            {"role": "system", "content": "You are an expert prompt engineer."},
            {"role": "user", "content": prompt_text}
        ]

        try:
            response = await self._call_llm(messages)
            return response.strip() if response else None
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return None

    async def _create_standalone_prompt(
        self,
        affected_capability: str,
        gap_description: str,
        challenge_context: str,
        start_time: float
    ) -> BuildResult:
        """
        Fallback: Create a standalone prompt when no suitable agent exists.

        This prompt will be recognized via affected_capability metadata.
        """
        prompt_name = f"prompt_{affected_capability.replace(' ', '_').lower()}"

        # Generate prompt content
        if self._call_llm:
            messages = [
                {"role": "system", "content": "You are an expert prompt engineer."},
                {"role": "user", "content": f"""Create a prompt for an AI agent that handles: {affected_capability}

Gap description: {gap_description}

Context: {challenge_context[:500]}

The prompt should:
1. Clearly define the agent's role
2. Provide specific instructions for {affected_capability}
3. Include expected input/output format
4. Be concise but comprehensive

Output ONLY the prompt text."""}
            ]
            content = await self._call_llm(messages)
        else:
            content = f"You are an agent specialized in {affected_capability}.\n\n{gap_description}"

        prompt = Prompt(
            id=str(uuid.uuid4()),
            name=prompt_name,
            content=content or f"Agent for {affected_capability}",
            prompt_metadata={
                "built_by": "agent_prompt_improver",
                "affected_capability": affected_capability,
                "gap_description": gap_description[:200],
                "standalone": True,  # Not attached to any agent
                "provisional": True,
            },
            is_active=True
        )
        async with self.session_factory() as db:
            db.add(prompt)
            await db.commit()
            await db.refresh(prompt)

        duration = time.time() - start_time
        logger.info(
            f"Created standalone prompt '{prompt_name}' for capability '{affected_capability}'"
        )

        return BuildResult(
            success=True,
            artifact_id=prompt.id,
            artifact_type="prompt",
            failure_reason=None,
            approach_used="standalone_prompt",
            duration_seconds=duration
        )

    async def _create_prompt_for_agent(
        self,
        agent: Agent,
        affected_capability: str,
        gap_description: str,
        challenge_context: str,
        start_time: float
    ) -> BuildResult:
        """Create a new prompt for an agent that doesn't have one."""
        # Generate prompt content
        if self._call_llm:
            messages = [
                {"role": "system", "content": "You are an expert prompt engineer."},
                {"role": "user", "content": f"""Create a prompt for agent "{agent.name}" that handles: {affected_capability}

Agent name: {agent.name}

Gap description: {gap_description}

Context: {challenge_context[:500]}

The prompt should:
1. Define the agent's role based on its name and capabilities
2. Provide specific instructions for {affected_capability}
3. Be concise but comprehensive

Output ONLY the prompt text."""}
            ]
            content = await self._call_llm(messages)
        else:
            content = f"You are {agent.name}, specialized in {affected_capability}."

        prompt = Prompt(
            id=str(uuid.uuid4()),
            name=f"{agent.name}_prompt",
            content=content or f"Agent {agent.name}",
            prompt_metadata={
                "built_by": "agent_prompt_improver",
                "for_agent": agent.id,
                "affected_capability": affected_capability,
                "provisional": True,
            },
            is_active=True
        )
        async with self.session_factory() as db:
            db.add(prompt)

            # Update agent with new prompt
            await db.execute(
                update(Agent)
                .where(Agent.id == agent.id)
                .values(prompt_id=prompt.id)
            )

            await db.commit()
            await db.refresh(prompt)

        duration = time.time() - start_time
        logger.info(
            f"Created new prompt for agent '{agent.name}': {prompt.id[:8]}..."
        )

        return BuildResult(
            success=True,
            artifact_id=prompt.id,
            artifact_type="prompt",
            failure_reason=None,
            approach_used="new_agent_prompt",
            duration_seconds=duration,
            bound_to_agent_id=agent.id
        )

    async def _log_prompt_improvement(
        self,
        agent: Agent,
        old_prompt_id: str,
        new_prompt_id: str,
        affected_capability: str
    ) -> None:
        """Log prompt improvement in topology change log."""
        try:
            from app.orchestration.topology.service import TopologyService
            async with self.session_factory() as db:
                topology_service = TopologyService(db)
                await topology_service.log_agent_updated(
                    agent=agent,
                    previous_state={
                        "prompt_id": old_prompt_id,
                    },
                    source="system_generated",
                    triggered_by=f"weak_prompt:{affected_capability}",
                    details={
                        "modification_type": "prompt_improved",
                        "old_prompt_id": old_prompt_id,
                        "new_prompt_id": new_prompt_id,
                        "affected_capability": affected_capability,
                    }
                )
        except Exception as e:
            logger.warning(f"Failed to log prompt improvement: {e}")
