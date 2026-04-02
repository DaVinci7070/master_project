"""
AgentService for runtime agent management.

Provides CRUD operations and activate/deactivate functionality for agents.
"""
import uuid
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sql.versioned_models import Agent
from app.models.schemas.versioned_schemas import AgentCreate, AgentUpdate, AgentResponse


class AgentService:
    """Service for managing Agent entities with CRUD and activation operations."""

    def __init__(self, session: AsyncSession):
        """
        Initialize AgentService with database session.

        Args:
            session: SQLAlchemy async session for database operations.
        """
        self.session = session

    async def create(self, agent_data: AgentCreate) -> Agent:
        """
        Create a new agent.

        Args:
            agent_data: Agent creation data.

        Returns:
            Created Agent instance.
        """
        agent = Agent(
            id=str(uuid.uuid4()),
            name=agent_data.name,
            capabilities=agent_data.capabilities,
            dependencies=agent_data.dependencies,
            io_schema=agent_data.io_schema,
            is_active=agent_data.is_active,
            prompt_id=agent_data.prompt_id,
        )
        self.session.add(agent)
        await self.session.commit()
        await self.session.refresh(agent)
        return agent

    async def get_by_id(self, agent_id: str) -> Optional[Agent]:
        """
        Get agent by ID.

        Args:
            agent_id: UUID of the agent.

        Returns:
            Agent instance or None if not found.
        """
        result = await self.session.execute(
            select(Agent).where(Agent.id == agent_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Optional[Agent]:
        """
        Get agent by name.

        Args:
            name: Unique name of the agent.

        Returns:
            Agent instance or None if not found.
        """
        result = await self.session.execute(
            select(Agent).where(Agent.name == name)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Agent]:
        """
        List all agents.

        Returns:
            List of all Agent instances.
        """
        result = await self.session.execute(select(Agent))
        return list(result.scalars().all())

    async def list_active(self) -> list[Agent]:
        """
        List only active agents.

        Returns:
            List of active Agent instances.
        """
        result = await self.session.execute(
            select(Agent).where(Agent.is_active == True)
        )
        return list(result.scalars().all())

    async def update(self, agent_id: str, agent_data: AgentUpdate) -> Optional[Agent]:
        """
        Update an existing agent.

        Args:
            agent_id: UUID of the agent to update.
            agent_data: Update data (only non-None fields are updated).

        Returns:
            Updated Agent instance or None if not found.
        """
        agent = await self.get_by_id(agent_id)
        if not agent:
            return None

        update_data = agent_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(agent, field, value)

        await self.session.commit()
        await self.session.refresh(agent)
        return agent

    async def delete(self, agent_id: str) -> bool:
        """
        Delete an agent.

        Args:
            agent_id: UUID of the agent to delete.

        Returns:
            True if deleted, False if not found.
        """
        agent = await self.get_by_id(agent_id)
        if not agent:
            return False

        await self.session.delete(agent)
        await self.session.commit()
        return True

    async def activate(self, agent_id: str) -> Optional[Agent]:
        """
        Activate an agent at runtime.

        Sets is_active=True for the agent, enabling it for use.

        Args:
            agent_id: UUID of the agent to activate.

        Returns:
            Activated Agent instance or None if not found.
        """
        agent = await self.get_by_id(agent_id)
        if not agent:
            return None

        agent.is_active = True
        await self.session.commit()
        await self.session.refresh(agent)
        return agent

    async def deactivate(self, agent_id: str) -> Optional[Agent]:
        """
        Deactivate an agent at runtime.

        Sets is_active=False for the agent, disabling it from use.

        Args:
            agent_id: UUID of the agent to deactivate.

        Returns:
            Deactivated Agent instance or None if not found.
        """
        agent = await self.get_by_id(agent_id)
        if not agent:
            return None

        agent.is_active = False
        await self.session.commit()
        await self.session.refresh(agent)
        return agent
