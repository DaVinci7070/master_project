"""
Reset script: Deletes all system-generated agents, skills, and their associated prompts.
Keeps only 'initial' (default/seeded) entities.

Usage:
    python -m scripts.reset_system_generated
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.sql.versioned_models import Agent, Skill, Prompt


async def reset_system_generated():
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        async with session.begin():
            # Count before deletion
            agent_count = (await session.execute(
                select(func.count()).select_from(Agent).where(Agent.source == "system_generated")
            )).scalar()

            skill_count = (await session.execute(
                select(func.count()).select_from(Skill)
            )).scalar()

            initial_agent_count = (await session.execute(
                select(func.count()).select_from(Agent).where(Agent.source == "initial")
            )).scalar()

            print(f"Found {agent_count} system-generated agents")
            print(f"Found {skill_count} skills (all will be deleted)")
            print(f"Found {initial_agent_count} initial/default agents (will be kept)")

            if agent_count == 0 and skill_count == 0:
                print("\nNothing to delete. System is already clean.")
                return

            # Get prompt IDs linked to system-generated agents (to clean up)
            sg_prompt_ids = (await session.execute(
                select(Agent.prompt_id).where(
                    Agent.source == "system_generated",
                    Agent.prompt_id.isnot(None)
                )
            )).scalars().all()

            # Delete system-generated agents
            deleted_agents = (await session.execute(
                delete(Agent).where(Agent.source == "system_generated")
            )).rowcount

            # Delete all skills (skills don't have a 'source' field, so all are system-generated)
            deleted_skills = (await session.execute(
                delete(Skill)
            )).rowcount

            # Delete orphaned prompts that were only used by system-generated agents
            deleted_prompts = 0
            if sg_prompt_ids:
                # Only delete prompts not referenced by any remaining agent
                for prompt_id in sg_prompt_ids:
                    remaining = (await session.execute(
                        select(func.count()).select_from(Agent).where(Agent.prompt_id == prompt_id)
                    )).scalar()
                    if remaining == 0:
                        await session.execute(delete(Prompt).where(Prompt.id == prompt_id))
                        deleted_prompts += 1

            # Also clean up topology change log entries if table exists
            try:
                from app.models.sql.topology_models import TopologyChangeLog
                deleted_logs = (await session.execute(
                    delete(TopologyChangeLog)
                )).rowcount
                print(f"Deleted {deleted_logs} topology change log entries")
            except Exception:
                pass

            # Clean up agent events if table exists
            try:
                from app.models.sql.agent_event_models import AgentExecutionEvent
                deleted_events = (await session.execute(
                    delete(AgentExecutionEvent)
                )).rowcount
                print(f"Deleted {deleted_events} agent execution events")
            except Exception:
                pass

        print(f"\nDeleted {deleted_agents} system-generated agents")
        print(f"Deleted {deleted_skills} skills")
        print(f"Deleted {deleted_prompts} orphaned prompts")
        print("\nSystem reset complete. Only default agents remain.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(reset_system_generated())
