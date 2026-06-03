import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.models.sql.topology_models import TopologyChangeLog
from app.models.sql.versioned_models import Agent, Skill, Prompt

logger = logging.getLogger(__name__)


class TopologyService:
    """Service for logging and querying topology changes."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def log_agent_created(
        self,
        agent: Agent,
        source: str = "manual",
        triggered_by: Optional[str] = None,
        details: Optional[dict] = None
    ) -> TopologyChangeLog:
        """Log creation of a new agent."""
        log_entry = TopologyChangeLog(
            id=str(uuid.uuid4()),
            change_type="agent_created",
            entity_type="agent",
            entity_id=agent.id,
            entity_name=agent.name,
            source=source,
            triggered_by=triggered_by,
            change_details=details or {},
            previous_state=None,
            new_state={
                "name": agent.name,
                "capabilities": [],
                "dependencies": agent.dependencies,
                "is_active": agent.is_active,
                "source": agent.source,
            }
        )
        self.db.add(log_entry)
        await self.db.flush()
        logger.info(f"Logged agent creation: {agent.name} (source={source})")
        return log_entry

    async def log_agent_updated(
        self,
        agent: Agent,
        previous_state: dict,
        source: str = "manual",
        triggered_by: Optional[str] = None,
        details: Optional[dict] = None
    ) -> TopologyChangeLog:
        """Log update to an existing agent."""
        log_entry = TopologyChangeLog(
            id=str(uuid.uuid4()),
            change_type="agent_updated",
            entity_type="agent",
            entity_id=agent.id,
            entity_name=agent.name,
            source=source,
            triggered_by=triggered_by,
            change_details=details or {},
            previous_state=previous_state,
            new_state={
                "name": agent.name,
                "capabilities": [],
                "dependencies": agent.dependencies,
                "is_active": agent.is_active,
                "source": agent.source,
            }
        )
        self.db.add(log_entry)
        await self.db.flush()
        logger.info(f"Logged agent update: {agent.name}")
        return log_entry

    async def log_agent_deactivated(
        self,
        agent: Agent,
        source: str = "manual",
        triggered_by: Optional[str] = None,
        reason: Optional[str] = None
    ) -> TopologyChangeLog:
        """Log deactivation of an agent."""
        log_entry = TopologyChangeLog(
            id=str(uuid.uuid4()),
            change_type="agent_deactivated",
            entity_type="agent",
            entity_id=agent.id,
            entity_name=agent.name,
            source=source,
            triggered_by=triggered_by,
            change_details={"reason": reason} if reason else {},
            previous_state={"is_active": True},
            new_state={"is_active": False}
        )
        self.db.add(log_entry)
        await self.db.flush()
        logger.info(f"Logged agent deactivation: {agent.name}")
        return log_entry

    async def log_skill_created(
        self,
        skill: Skill,
        source: str = "manual",
        triggered_by: Optional[str] = None,
        details: Optional[dict] = None
    ) -> TopologyChangeLog:
        """Log creation of a new skill."""
        log_entry = TopologyChangeLog(
            id=str(uuid.uuid4()),
            change_type="skill_created",
            entity_type="skill",
            entity_id=skill.id,
            entity_name=skill.name,
            source=source,
            triggered_by=triggered_by,
            change_details=details or {},
            previous_state=None,
            new_state={
                "name": skill.name,
                "description": skill.description,
                "is_active": skill.is_active,
            }
        )
        self.db.add(log_entry)
        await self.db.flush()
        logger.info(f"Logged skill creation: {skill.name}")
        return log_entry

    async def log_prompt_created(
        self,
        prompt: Prompt,
        source: str = "manual",
        triggered_by: Optional[str] = None,
        details: Optional[dict] = None
    ) -> TopologyChangeLog:
        """Log creation of a new prompt."""
        log_entry = TopologyChangeLog(
            id=str(uuid.uuid4()),
            change_type="prompt_created",
            entity_type="prompt",
            entity_id=prompt.id,
            entity_name=prompt.name,
            source=source,
            triggered_by=triggered_by,
            change_details=details or {},
            previous_state=None,
            new_state={
                "name": prompt.name,
                "is_active": prompt.is_active,
            }
        )
        self.db.add(log_entry)
        await self.db.flush()
        logger.info(f"Logged prompt creation: {prompt.name}")
        return log_entry

    async def get_recent_changes(
        self,
        limit: int = 50,
        entity_type: Optional[str] = None,
        change_type: Optional[str] = None,
        source: Optional[str] = None
    ) -> list[TopologyChangeLog]:
        """Get recent topology changes with optional filters."""
        query = select(TopologyChangeLog).order_by(desc(TopologyChangeLog.created_at))

        if entity_type:
            query = query.where(TopologyChangeLog.entity_type == entity_type)
        if change_type:
            query = query.where(TopologyChangeLog.change_type == change_type)
        if source:
            query = query.where(TopologyChangeLog.source == source)

        query = query.limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_changes_for_entity(
        self,
        entity_type: str,
        entity_id: str
    ) -> list[TopologyChangeLog]:
        """Get all changes for a specific entity."""
        query = select(TopologyChangeLog).where(
            TopologyChangeLog.entity_type == entity_type,
            TopologyChangeLog.entity_id == entity_id
        ).order_by(desc(TopologyChangeLog.created_at))

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_system_generated_agents(self) -> list[Agent]:
        """Get all agents created by the system."""
        query = select(Agent).where(Agent.source == "system_generated")
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_topology_stats(self) -> dict:
        """Get statistics about topology and changes."""
        agents_query = select(Agent)
        agents_result = await self.db.execute(agents_query)
        agents = list(agents_result.scalars().all())

        initial_count = sum(1 for a in agents if a.source == "initial" or a.source is None)
        system_count = sum(1 for a in agents if a.source == "system_generated")
        manual_count = sum(1 for a in agents if a.source == "manual")

        recent_query = select(TopologyChangeLog).order_by(
            desc(TopologyChangeLog.created_at)
        ).limit(100)
        recent_result = await self.db.execute(recent_query)
        recent_changes = list(recent_result.scalars().all())

        return {
            "agents": {
                "total": len(agents),
                "active": sum(1 for a in agents if a.is_active),
                "by_source": {
                    "initial": initial_count,
                    "system_generated": system_count,
                    "manual": manual_count
                }
            },
            "recent_changes": {
                "count": len(recent_changes),
                "by_type": {}
            }
        }
