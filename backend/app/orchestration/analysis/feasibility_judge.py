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

FEASIBILITY_PROMPT = """You are verifying whether an agent can actually perform a specific action.

## Required Action
{action}
(Type: execution — requires running code or producing computed artifacts)

## Agent: {agent_name}
Description: {agent_description}
Capabilities declared: {agent_capabilities}

## Available Tools/Skills bound to this agent:
{skill_list}

Can this agent perform the required action using its available tools/skills?

Rules:
- An agent that can WRITE ABOUT or ANALYZE something is NOT the same as one that can BUILD or CREATE it
- If the action requires running code (database operations, file creation, data computation), the agent MUST have an executable skill/tool for it
- A prompt-only agent (no skills) CANNOT perform execution tasks — it can only reason and write text
- Name the SPECIFIC tool or skill the agent would use. If none exists, it cannot perform the action.

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

        # Get agent details and bound skills
        agent_info = await self._get_agent_info(agent_id)
        skill_list = await self._get_agent_skills(agent_id)

        prompt = FEASIBILITY_PROMPT.format(
            action=match.required_capability,
            agent_name=agent_info.get("name", agent_id),
            agent_description=agent_info.get("description", "No description available"),
            agent_capabilities=", ".join(agent_info.get("capabilities", [])),
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
                messages, FeasibilityLLMResponse, temperature=0.1,
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
            # On error, assume infeasible for execution tasks (safe default)
            return FeasibilityResult(
                required_capability=match.required_capability,
                matched_agent_id=agent_id,
                feasible=False,
                reason=f"Feasibility check error: {e}",
            )

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

            # Check if it's a skill: or prompt: prefixed ID
            if agent_id.startswith("skill:") or agent_id.startswith("prompt:"):
                return {
                    "name": agent_id,
                    "description": f"Capability provider: {agent_id}",
                    "capabilities": [],
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
                # Skills are bound to agents — check binding
                bound_agent = skill_data.get("agent_id") or skill_data.get("bound_to")
                if bound_agent == agent_id:
                    name = skill_data.get("name", skill_id)
                    desc = skill_data.get("description", "No description")
                    agent_skills.append(f"- {name}: {desc}")

            # Also check skill bindings in database
            from sqlalchemy import select
            from app.models.sql.skill_build_models import SkillBinding

            db = self.topology.db
            result = await db.execute(
                select(SkillBinding).where(SkillBinding.agent_id == agent_id)
            )
            bindings = result.scalars().all()

            for binding in bindings:
                if binding.skill_id not in all_skills:
                    agent_skills.append(
                        f"- skill:{binding.skill_id} (bound, details not cached)"
                    )

            return "\n".join(agent_skills) if agent_skills else ""

        except Exception as e:
            logger.warning(f"Failed to get skills for agent {agent_id}: {e}")
            return ""
