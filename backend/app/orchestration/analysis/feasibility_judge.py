"""
LLM-based feasibility judge for execution-type capabilities.

Verifies whether agents actually have tools/skills to perform execution tasks,
preventing false CAN_DO verdicts from embedding similarity alone.

When CapabilityMatcher reports a high similarity score for an execution-type
capability, the FeasibilityJudge asks the LLM: "Can this agent actually
perform this action using its available tools?" If no tool exists, the
capability is marked infeasible and routes to Developer Team for skill building.
"""
import logging
from typing import Callable, Awaitable, Optional

from app.orchestration.analysis.models import (
    AssessmentContext, CapabilityMatch, CapabilityType, FeasibilityResult,
    FeasibilityLLMResponse,
)
from app.orchestration.topology.loader import TopologyLoader

logger = logging.getLogger(__name__)

FEASIBILITY_PROMPT = """You are verifying whether an agent can actually perform a SPECIFIC action.

## Required Action
{action}

## Agent: {agent_name}
Capabilities declared: {agent_capabilities}

## Agent System Prompt (excerpt)
{agent_prompt_excerpt}

## Available Tools/Skills bound to this agent:
{skill_list}

Can this agent perform the EXACT required action using its available tools?

Rules:
1. If the action can be accomplished purely through REASONING and TEXT GENERATION (analyzing, summarizing, writing reports, extracting information, generating documents), the agent IS feasible if its prompt covers this domain — no tools needed.
2. If the action requires RUNNING CODE, DATABASE ACCESS, FILE I/O, API CALLS, or DATA COMPUTATION, the agent MUST have an executable skill/tool that SPECIFICALLY covers this operation.
3. Match the SPECIFIC operation, not the general domain:
   - "read CSV files from directory" requires a FILE READING skill — a DATABASE skill does NOT cover this
   - "execute SQL queries" requires a DATABASE skill — a FILE READING skill does NOT cover this
   - "call external API" requires an API/HTTP skill — a DATABASE skill does NOT cover this
   - "transform and load data" requires BOTH reading the source AND writing to the target — check BOTH ends
4. A skill that operates on databases CANNOT read files from the filesystem (and vice versa).
5. If no tool/skill in the list can perform the EXACT I/O operation required, the agent is NOT feasible.

Respond with JSON only, no markdown:
{{"feasible": true/false, "tool_name": "name of the specific tool/skill or null", "reason": "brief explanation"}}"""


class FeasibilityJudge:
    """
    Verifies that execution-type capabilities have actual tool/skill backing.

    Only called for capabilities where:
    - type == EXECUTION
    - similarity_score >= CAN_DO_THRESHOLD (embedding match looks good)

    Knowledge-type capabilities skip this check entirely since they're
    served by LLM-based reasoning which all agents can do.
    """

    def __init__(
        self,
        topology_loader: Optional[TopologyLoader] = None,
        structured_llm_fn: Optional[Callable] = None,
    ):
        self._structured_llm_fn = structured_llm_fn
        self.topology = topology_loader

    async def verify_execution_capabilities(
        self,
        context: AssessmentContext,
        capability_matches: list[CapabilityMatch],
    ) -> list[FeasibilityResult]:
        """
        Verify that execution-type capability matches have real tool backing.

        Args:
            context: Full assessment context
            capability_matches: Matches to verify (pre-filtered to execution type)

        Returns:
            List of FeasibilityResult for each checked capability
        """
        if not self._structured_llm_fn:
            logger.warning("No LLM function for feasibility judge, skipping verification")
            return []

        results = []
        for match in capability_matches:
            if match.capability_type != CapabilityType.EXECUTION:
                continue
            if not match.matched_agent_id:
                continue

            result = await self._judge_single(match)
            results.append(result)

            if not result.feasible:
                logger.info(
                    f"INFEASIBLE: '{match.required_capability}' "
                    f"cannot be performed by agent '{match.matched_agent_id}': "
                    f"{result.reason}"
                )

        feasible_count = sum(1 for r in results if r.feasible)
        infeasible_count = len(results) - feasible_count
        logger.info(
            f"Feasibility check complete: {feasible_count} feasible, "
            f"{infeasible_count} infeasible out of {len(results)} execution capabilities"
        )

        return results

    async def _judge_single(self, match: CapabilityMatch) -> FeasibilityResult:
        """Judge feasibility of a single capability match."""
        agent_id = match.matched_agent_id

        # Pseudo-Entities (skill:xxx, prompt:xxx) zum echten Agent aufloesen
        if agent_id.startswith("skill:") or agent_id.startswith("prompt:"):
            real_agent_id = await self._resolve_to_real_agent(agent_id)
            if real_agent_id:
                logger.info(
                    f"Resolved '{agent_id}' to real agent '{real_agent_id}'"
                )
                agent_id = real_agent_id
            else:
                # Skill/Prompt existiert aber ist keinem Agent zugewiesen.
                # Trotzdem prüfen ob die Capability zur Aktion passt —
                # Embedding-Similarity allein reicht nicht (z.B. DB-Skill ≠ File-I/O).
                logger.info(
                    f"'{match.required_capability}' matched to unbound '{match.matched_agent_id}' "
                    f"— verifying via LLM"
                )

        # Get agent details and bound skills
        agent_info = await self._get_agent_info(agent_id)
        skill_list = await self._get_agent_skills(agent_id)
        prompt_excerpt = await self._get_agent_prompt_excerpt(agent_id)

        prompt = FEASIBILITY_PROMPT.format(
            action=match.required_capability,
            agent_name=agent_info.get("name", agent_id),
            agent_capabilities=", ".join(agent_info.get("capabilities", [])),
            agent_prompt_excerpt=prompt_excerpt or "No prompt available.",
            skill_list=skill_list if skill_list else "No executable skills/tools bound to this agent.",
        )

        messages = [
            {
                "role": "system",
                "content": "You verify agent capabilities precisely.",
            },
            {"role": "user", "content": prompt},
        ]

        try:
            parsed = await self._structured_llm_fn(
                messages, FeasibilityLLMResponse, temperature=0.0,
            )
            return FeasibilityResult(
                required_capability=match.required_capability,
                matched_agent_id=agent_id,
                feasible=parsed.feasible,
                tool_name=parsed.tool_name,
                reason=parsed.reason,
            )

        except Exception as e:
            logger.error(f"Feasibility judge failed for '{match.required_capability}': {e}")
            return FeasibilityResult(
                required_capability=match.required_capability,
                matched_agent_id=agent_id,
                feasible=True,
                reason=f"Feasibility-Check fehlgeschlagen, Ausfuehrung wird versucht: {e}",
            )

    async def _resolve_to_real_agent(self, pseudo_id: str) -> Optional[str]:
        """Loest skill:xxx / prompt:xxx Pseudo-IDs zum zugehoerigen echten Agent auf."""
        if not self.topology:
            return None

        try:
            from sqlalchemy import select
            from app.models.sql.versioned_models import Skill, Prompt, Agent

            async with self.topology.session_factory() as db:
                if pseudo_id.startswith("skill:"):
                    skill_id = pseudo_id[len("skill:"):]
                    result = await db.execute(
                        select(Skill).where(Skill.id == skill_id)
                    )
                    skill = result.scalar_one_or_none()
                    if skill and skill.skill_metadata:
                        target = (
                            skill.skill_metadata.get("target_agent_id")
                            or skill.skill_metadata.get("assigned_agent")
                        )
                        if target:
                            return target

                elif pseudo_id.startswith("prompt:"):
                    prompt_id = pseudo_id[len("prompt:"):]
                    result = await db.execute(
                        select(Agent.id).where(
                            Agent.prompt_id == prompt_id,
                            Agent.is_active == True,
                        )
                    )
                    agent_id = result.scalar_one_or_none()
                    if agent_id:
                        return agent_id

        except Exception as e:
            logger.warning(f"Pseudo-Entity '{pseudo_id}' konnte nicht aufgeloest werden: {e}")

        return None

    async def _get_agent_prompt_excerpt(self, agent_id: str) -> Optional[str]:
        """Ersten Abschnitt des Agent-Prompts laden (zeigt Domaene/Faehigkeiten)."""
        if not self.topology:
            return None
        try:
            from sqlalchemy import select
            from app.models.sql.versioned_models import Agent, Prompt

            async with self.topology.session_factory() as db:
                result = await db.execute(
                    select(Prompt.content)
                    .join(Agent, Agent.prompt_id == Prompt.id)
                    .where(Agent.id == agent_id)
                )
                content = result.scalar_one_or_none()
                if content:
                    return content[:500]
        except Exception as e:
            logger.warning(f"Prompt-Auszug fuer {agent_id} nicht ladbar: {e}")
        return None

    async def _get_agent_info(self, agent_id: str) -> dict:
        """Get agent name, description, and capabilities from topology."""
        if not self.topology:
            return {"name": agent_id, "description": "", "capabilities": []}

        try:
            topology, _ = await self.topology.load()
            for agent in topology.get_active_agents():
                if agent.agent_id == agent_id:
                    return {
                        "name": agent.name or agent_id,
                        "description": getattr(agent, "description", "") or "",
                        "capabilities": agent.capabilities or [],
                    }

        except Exception as e:
            logger.warning(f"Failed to get agent info for {agent_id}: {e}")

        return {"name": agent_id, "description": "", "capabilities": []}

    async def _get_agent_skills(self, agent_id: str) -> str:
        """Get formatted list of skills bound to an agent."""
        if not self.topology:
            return ""

        try:
            # Get skills from topology loader cache
            all_skills = self.topology.get_all_loaded_skills()
            agent_skills = []

            for skill_id, skill_data in all_skills.items():
                # Skills sind ORM-Objekte — Attribut-Zugriff statt dict.get()
                meta = getattr(skill_data, "skill_metadata", None) or {}
                bound_agent = meta.get("agent_id") or meta.get("bound_to")
                if bound_agent == agent_id:
                    name = getattr(skill_data, "name", skill_id)
                    desc = getattr(skill_data, "description", None) or "No description"
                    agent_skills.append(f"- {name}: {desc}")

            # Also check skill bindings in database
            from sqlalchemy import select
            from app.models.sql.skill_build_models import SkillBinding

            async with self.topology.session_factory() as db:
                result = await db.execute(
                    select(SkillBinding).where(SkillBinding.agent_id == agent_id)
                )
                bindings = result.scalars().all()

            for binding in bindings:
                if binding.skill_id not in all_skills:
                    from app.models.sql.versioned_models import Skill
                    skill_result = await db.execute(
                        select(Skill).where(
                            Skill.id == binding.skill_id,
                            Skill.is_active == True,
                        )
                    )
                    skill_obj = skill_result.scalar_one_or_none()
                    if skill_obj:
                        agent_skills.append(
                            f"- {skill_obj.name}: {skill_obj.description or binding.capability}"
                        )
                    else:
                        agent_skills.append(
                            f"- skill:{binding.skill_id} (bound, skill not found)"
                        )

            return "\n".join(agent_skills) if agent_skills else ""

        except Exception as e:
            logger.warning(f"Failed to get skills for agent {agent_id}: {e}")
            return ""
