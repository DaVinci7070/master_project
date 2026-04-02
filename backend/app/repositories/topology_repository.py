"""Repository for topology persistence in database."""
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.sql.versioned_models import Agent, Prompt

logger = logging.getLogger(__name__)


class TopologyRepository:
    """
    Repository for loading agent topology from database.

    Reads from agents table to construct dynamic topology.
    """

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db

    async def get_all_active_agents(self) -> list[Agent]:
        """Get all active agents from database."""
        result = await self.db.execute(
            select(Agent).where(Agent.is_active == True)
        )
        return list(result.scalars().all())

    async def get_agent_by_id(self, agent_id: str) -> Optional[Agent]:
        """Get agent by ID."""
        result = await self.db.execute(
            select(Agent).where(Agent.id == agent_id)
        )
        return result.scalar_one_or_none()

    async def get_agent_by_name(self, name: str) -> Optional[Agent]:
        """Get agent by name."""
        result = await self.db.execute(
            select(Agent).where(Agent.name == name)
        )
        return result.scalar_one_or_none()

    async def get_agent_prompt(self, agent_id: str) -> Optional[Prompt]:
        """Get the prompt associated with an agent."""
        result = await self.db.execute(
            select(Agent).where(Agent.id == agent_id)
        )
        agent = result.scalar_one_or_none()

        if agent and agent.prompt_id:
            prompt_result = await self.db.execute(
                select(Prompt).where(Prompt.id == agent.prompt_id)
            )
            return prompt_result.scalar_one_or_none()
        return None

    async def get_agents_with_prompts(self) -> list[tuple[Agent, Optional[Prompt]]]:
        """Get all active agents with their prompts."""
        agents = await self.get_all_active_agents()
        results = []

        for agent in agents:
            prompt = None
            if agent.prompt_id:
                prompt_result = await self.db.execute(
                    select(Prompt).where(Prompt.id == agent.prompt_id)
                )
                prompt = prompt_result.scalar_one_or_none()
            results.append((agent, prompt))

        return results

    async def count_active_agents(self) -> int:
        """Count active agents."""
        agents = await self.get_all_active_agents()
        return len(agents)

    async def agent_exists(self, agent_id: str) -> bool:
        """Check if agent exists."""
        agent = await self.get_agent_by_id(agent_id)
        return agent is not None

    async def get_agent_dependencies(self, agent_id: str) -> list[str]:
        """Get dependencies for an agent (from dependencies JSON column)."""
        agent = await self.get_agent_by_id(agent_id)
        if agent:
            return agent.dependencies or []
        return []
