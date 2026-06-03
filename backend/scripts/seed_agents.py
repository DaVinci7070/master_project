#!/usr/bin/env python3
import argparse
import asyncio
import logging
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, delete

from app.core.config import settings
from app.models.sql.versioned_models import Agent, Prompt
from app.orchestration.agents.definitions import load_agents_by_team

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def get_db_session():
    """Create database session."""
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session


async def create_agent_with_prompt(session: AsyncSession, agent_data: dict, team: str) -> tuple[str, str]:
    """Agent und Prompt in der Datenbank anlegen oder aktualisieren."""
    result = await session.execute(
        select(Agent).where(Agent.name == agent_data["name"])
    )
    existing = result.scalar_one_or_none()
    if existing:
        if existing.prompt_id:
            prompt_result = await session.execute(
                select(Prompt).where(Prompt.id == existing.prompt_id)
            )
            existing_prompt = prompt_result.scalar_one_or_none()
            if existing_prompt and existing_prompt.content != agent_data["prompt"]:
                existing_prompt.content = agent_data["prompt"]
                logger.info(f"  Updated prompt for {agent_data['name']}")
        if existing.io_schema != agent_data["io_schema"]:
            existing.io_schema = agent_data["io_schema"]
            logger.info(f"  Updated io_schema for {agent_data['name']}")
        await session.commit()
        logger.info(f"  Synced {agent_data['name']} (already exists)")
        return existing.id, "skipped"

    prompt_id = str(uuid4())
    prompt = Prompt(
        id=prompt_id,
        name=f"{agent_data['name']}_prompt",
        content=agent_data["prompt"],
        prompt_metadata={"team": team, "agent": agent_data["name"]},
        is_active=True
    )
    session.add(prompt)

    agent_id = str(uuid4())
    agent = Agent(
        id=agent_id,
        name=agent_data["name"],
        dependencies=agent_data["dependencies"],
        io_schema=agent_data["io_schema"],
        prompt_id=prompt_id,
        is_active=True,
        agent_metadata={"team": team}
    )
    session.add(agent)

    await session.commit()
    logger.info(f"  Created {agent_data['name']} ({agent_id[:8]}...)")
    return agent_id, "created"


async def seed_agents():
    """Alle Agents in die Datenbank seeden."""
    logger.info("=" * 50)
    logger.info("Seeding Lumari Agents")
    logger.info("=" * 50)

    async for session in get_db_session():
        for team, label in [("main_team", "Main Team"), ("developer_team", "Developer Team")]:
            agents = load_agents_by_team(team)
            logger.info(f"\n[{label}]:")
            created = skipped = 0
            for agent_data in agents:
                _, status = await create_agent_with_prompt(session, agent_data, team)
                if status == "created":
                    created += 1
                else:
                    skipped += 1
            logger.info(f"  {created} created, {skipped} skipped")

        logger.info("\n" + "=" * 50)
        logger.info("Seeding Complete!")
        logger.info("=" * 50)


async def show_status():
    """Aktuellen Agent-Status anzeigen."""
    async for session in get_db_session():
        result = await session.execute(select(Agent))
        agents = result.scalars().all()

        logger.info("\n" + "=" * 50)
        logger.info("Current Agents in Database")
        logger.info("=" * 50)

        if not agents:
            logger.info("No agents found. Run: python scripts/seed_agents.py")
            return

        teams: dict[str, list] = {}
        for agent in agents:
            team = (agent.agent_metadata or {}).get("team", "unknown")
            teams.setdefault(team, []).append(agent)

        for team, members in sorted(teams.items()):
            logger.info(f"\n[{team}]")
            for a in members:
                status = "active" if a.is_active else "inactive"
                logger.info(f"  - {a.name} ({status})")

        logger.info(f"\nTotal: {len(agents)} agents")


async def reset_and_seed():
    """Alle Agents, Skills, Prompts löschen und neu seeden."""
    logger.info("Resetting agents...")

    async for session in get_db_session():
        from app.models.sql.skill_build_models import SkillBinding, SkillBuildAttempt
        from app.models.sql.versioned_models import Skill
        from app.models.sql.telemetry_models import ExecutionTelemetry
        from app.models.sql.execution_models import Execution
        from app.models.sql.gap_plan_models import CapabilityGapPlan
        from app.models.sql.analysis_models import AnalysisFinding
        from app.models.sql.improvement_models import ImprovementAttempt
        from app.models.sql.topology_models import TopologyChangeLog
        from app.models.sql.agent_event_models import AgentExecutionEvent

        for model in [
            SkillBinding, SkillBuildAttempt, AnalysisFinding,
            ImprovementAttempt, AgentExecutionEvent, ExecutionTelemetry,
            Execution, CapabilityGapPlan, TopologyChangeLog,
            Skill, Agent, Prompt,
        ]:
            await session.execute(delete(model))
        await session.commit()
        logger.info("Alle Tabellen geleert (Skills, Bindings, Agents, Prompts, Telemetrie, ...)")

    await seed_agents()


def main():
    parser = argparse.ArgumentParser(description="Seed Lumari agents")
    parser.add_argument("--status", action="store_true", help="Show current agents")
    parser.add_argument("--reset", action="store_true", help="Delete all and re-seed")

    args = parser.parse_args()

    if args.status:
        asyncio.run(show_status())
    elif args.reset:
        asyncio.run(reset_and_seed())
    else:
        asyncio.run(seed_agents())


if __name__ == "__main__":
    main()
