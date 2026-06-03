import logging
import yaml
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.sql.versioned_models import Agent, Prompt

logger = logging.getLogger(__name__)


class AgentMigrator:
    """
    Migrates hardcoded agent definitions to database.

    Idempotent: Can run multiple times safely (skips existing agents).
    """

    def __init__(self, db: AsyncSession):
        """Initialize migrator with database session."""
        self.db = db
        self._migrated_agents: list[str] = []
        self._migrated_prompts: list[str] = []
        self._skipped_agents: list[str] = []

    async def migrate_from_yaml(self, yaml_path: Path) -> dict[str, Any]:
        """
        Migrate agents from a YAML configuration file.

        Expected YAML format:
        ```yaml
        agents:
          - name: analyzer
            capabilities: [analyze, detect]
            dependencies: []
            io_schema:
              input: {...}
              output: {...}
            prompt: |
              You are an analyzer agent...
        ```

        Args:
            yaml_path: Path to YAML file

        Returns:
            Migration summary dict
        """
        if not yaml_path.exists():
            logger.error(f"YAML file not found: {yaml_path}")
            return {"error": f"File not found: {yaml_path}"}

        with open(yaml_path) as f:
            config = yaml.safe_load(f)

        agents_config = config.get("agents", [])
        if not agents_config:
            logger.warning(f"No agents found in {yaml_path}")
            return {"migrated": 0, "skipped": 0}

        for agent_config in agents_config:
            await self._migrate_agent(agent_config)

        await self.db.commit()

        return {
            "migrated_agents": self._migrated_agents.copy(),
            "migrated_prompts": self._migrated_prompts.copy(),
            "skipped_agents": self._skipped_agents.copy(),
            "total_migrated": len(self._migrated_agents),
            "total_skipped": len(self._skipped_agents)
        }

    async def _migrate_agent(self, config: dict[str, Any]) -> Optional[str]:
        """
        Migrate a single agent from config dict.

        Returns agent_id if migrated, None if skipped.
        """
        name = config.get("name")
        if not name:
            logger.warning("Agent config missing name, skipping")
            return None

        existing = await self._get_agent_by_name(name)
        if existing:
            logger.debug(f"Agent '{name}' already exists, skipping")
            self._skipped_agents.append(name)
            return None

        prompt_id = None
        prompt_content = config.get("prompt")
        if prompt_content:
            prompt_id = await self._create_prompt(
                name=f"{name}_prompt",
                content=prompt_content,
                metadata={"migrated_from": "yaml", "agent_name": name}
            )
            self._migrated_prompts.append(f"{name}_prompt")

        agent_id = str(uuid4())
        agent = Agent(
            id=agent_id,
            name=name,
            capabilities=config.get("capabilities", []),
            dependencies=config.get("dependencies", []),
            io_schema=config.get("io_schema", {}),
            is_active=config.get("is_active", True),
            prompt_id=prompt_id
        )

        self.db.add(agent)
        self._migrated_agents.append(name)
        logger.info(f"Migrated agent: {name}")

        return agent_id

    async def _get_agent_by_name(self, name: str) -> Optional[Agent]:
        """Check if agent exists by name."""
        result = await self.db.execute(
            select(Agent).where(Agent.name == name)
        )
        return result.scalar_one_or_none()

    async def _create_prompt(
        self,
        name: str,
        content: str,
        metadata: Optional[dict] = None
    ) -> str:
        """Create prompt in database."""
        result = await self.db.execute(
            select(Prompt).where(Prompt.name == name)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing.id

        prompt_id = str(uuid4())
        prompt = Prompt(
            id=prompt_id,
            name=name,
            content=content,
            prompt_metadata=metadata or {},
            is_active=True
        )
        self.db.add(prompt)
        return prompt_id

    async def migrate_inline_agents(
        self,
        agents: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Migrate agents from inline config (not YAML file).

        Useful for programmatic migration.
        """
        for agent_config in agents:
            await self._migrate_agent(agent_config)

        await self.db.commit()

        return {
            "migrated_agents": self._migrated_agents.copy(),
            "migrated_prompts": self._migrated_prompts.copy(),
            "skipped_agents": self._skipped_agents.copy()
        }

    async def migrate_prompt_only(
        self,
        name: str,
        content: str,
        parent_id: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> str:
        """
        Migrate a standalone prompt.

        Supports parent-child relationships for prompt versioning.

        Returns:
            Created prompt ID
        """
        result = await self.db.execute(
            select(Prompt).where(Prompt.name == name)
        )
        existing = result.scalar_one_or_none()
        if existing:
            logger.debug(f"Prompt '{name}' already exists, returning existing")
            return existing.id

        prompt_id = str(uuid4())
        prompt = Prompt(
            id=prompt_id,
            parent_id=parent_id,
            name=name,
            content=content,
            prompt_metadata=metadata or {"migrated": True},
            is_active=True
        )
        self.db.add(prompt)
        await self.db.commit()

        self._migrated_prompts.append(name)
        logger.info(f"Migrated prompt: {name}")

        return prompt_id

    async def get_migration_status(self) -> dict[str, Any]:
        """Get current migration status from database."""
        agents_result = await self.db.execute(select(Agent))
        agents = list(agents_result.scalars().all())

        prompts_result = await self.db.execute(select(Prompt))
        prompts = list(prompts_result.scalars().all())

        migrated_agents = [
            a for a in agents
            if a.io_schema and a.io_schema.get("migrated_from") == "yaml"
        ]

        return {
            "total_agents": len(agents),
            "total_prompts": len(prompts),
            "migrated_agents": len(migrated_agents),
            "agent_names": [a.name for a in agents],
            "prompt_names": [p.name for p in prompts]
        }
