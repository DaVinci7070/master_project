#!/usr/bin/env python3
"""
CLI script to migrate hardcoded agents to database.

Usage:
    python scripts/migrate_hardcoded_agents.py --yaml config/agents.yaml
    python scripts/migrate_hardcoded_agents.py --scan-prompts
    python scripts/migrate_hardcoded_agents.py --status
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.orchestration.migration.agent_migrator import AgentMigrator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def get_db_session():
    """Create database session."""
    engine = create_async_engine(
        settings.database_url,
        echo=False
    )
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session


async def migrate_from_yaml(yaml_path: str):
    """Migrate agents from YAML file."""
    path = Path(yaml_path)
    if not path.exists():
        logger.error(f"File not found: {yaml_path}")
        return

    async for session in get_db_session():
        migrator = AgentMigrator(session)
        result = await migrator.migrate_from_yaml(path)

        print("\n=== Migration Results ===")
        print(f"Migrated agents: {result.get('total_migrated', 0)}")
        print(f"Skipped agents: {result.get('total_skipped', 0)}")

        if result.get('migrated_agents'):
            print("\nMigrated:")
            for name in result['migrated_agents']:
                print(f"  - {name}")

        if result.get('skipped_agents'):
            print("\nSkipped (already exist):")
            for name in result['skipped_agents']:
                print(f"  - {name}")


async def scan_prompts_directory(prompts_dir: str):
    """Scan prompts directory and migrate all .txt files."""
    dir_path = Path(prompts_dir)
    if not dir_path.exists():
        logger.error(f"Directory not found: {prompts_dir}")
        return

    prompt_files = list(dir_path.glob("**/*.txt")) + list(dir_path.glob("**/*.md"))
    logger.info(f"Found {len(prompt_files)} prompt files")

    async for session in get_db_session():
        migrator = AgentMigrator(session)

        for prompt_file in prompt_files:
            name = prompt_file.stem
            content = prompt_file.read_text()
            await migrator.migrate_prompt_only(
                name=name,
                content=content,
                metadata={"source_file": str(prompt_file)}
            )

        print(f"\nMigrated {len(migrator._migrated_prompts)} prompts")


async def show_status():
    """Show current migration status."""
    async for session in get_db_session():
        migrator = AgentMigrator(session)
        status = await migrator.get_migration_status()

        print("\n=== Migration Status ===")
        print(f"Total agents in database: {status['total_agents']}")
        print(f"Total prompts in database: {status['total_prompts']}")

        if status['agent_names']:
            print("\nAgents:")
            for name in status['agent_names']:
                print(f"  - {name}")

        if status['prompt_names']:
            print("\nPrompts:")
            for name in status['prompt_names'][:10]:  # Limit to 10
                print(f"  - {name}")
            if len(status['prompt_names']) > 10:
                print(f"  ... and {len(status['prompt_names']) - 10} more")


async def migrate_default_agents():
    """Migrate a set of default agents for the system."""
    default_agents = [
        {
            "name": "analyzer",
            "capabilities": ["analyze", "detect_patterns", "extract_insights"],
            "dependencies": [],
            "io_schema": {
                "input": {"type": "object", "properties": {"text": {"type": "string"}}},
                "output": {"type": "object", "properties": {"findings": {"type": "array"}}},
                "consumes": [],
                "produces": ["analysis_result"]
            },
            "prompt": "You are an analyzer agent. Your job is to analyze input and extract insights."
        },
        {
            "name": "validator",
            "capabilities": ["validate", "verify"],
            "dependencies": ["analyzer"],
            "io_schema": {
                "input": {"type": "object"},
                "output": {"type": "object", "properties": {"valid": {"type": "boolean"}}},
                "consumes": ["analysis_result"],
                "produces": ["validation_result"]
            },
            "prompt": "You are a validator agent. Your job is to verify analysis results."
        },
        {
            "name": "reporter",
            "capabilities": ["summarize", "report"],
            "dependencies": ["validator"],
            "io_schema": {
                "input": {"type": "object"},
                "output": {"type": "object", "properties": {"report": {"type": "string"}}},
                "consumes": ["validation_result"],
                "produces": ["final_report"]
            },
            "prompt": "You are a reporter agent. Your job is to generate final reports."
        }
    ]

    async for session in get_db_session():
        migrator = AgentMigrator(session)
        result = await migrator.migrate_inline_agents(default_agents)

        print("\n=== Default Agent Migration ===")
        print(f"Migrated: {len(result.get('migrated_agents', []))}")
        print(f"Skipped: {len(result.get('skipped_agents', []))}")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate hardcoded agents to database"
    )
    parser.add_argument(
        "--yaml",
        type=str,
        help="Path to YAML config file"
    )
    parser.add_argument(
        "--scan-prompts",
        type=str,
        help="Path to prompts directory to scan"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show migration status"
    )
    parser.add_argument(
        "--defaults",
        action="store_true",
        help="Migrate default agents"
    )

    args = parser.parse_args()

    if args.yaml:
        asyncio.run(migrate_from_yaml(args.yaml))
    elif args.scan_prompts:
        asyncio.run(scan_prompts_directory(args.scan_prompts))
    elif args.status:
        asyncio.run(show_status())
    elif args.defaults:
        asyncio.run(migrate_default_agents())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
