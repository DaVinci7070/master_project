"""
Migration script: Add SoK skill columns to existing database.

Adds: skill_type, applicability, instructions, termination, interface, dependencies
to the skills table (and its Continuum version table).

Idempotent — safe to run multiple times.
"""
import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from app.dependencies.dependencies import async_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Columns to add to both 'skills' and 'skills_version'
NEW_COLUMNS = [
    ("skill_type", "VARCHAR(20) NOT NULL DEFAULT 'functional'"),
    ("applicability", "TEXT"),
    ("instructions", "TEXT"),
    ("termination", "TEXT"),
    ("interface", "JSON"),
    ("dependencies", "JSON"),
]


async def get_existing_columns(conn, table_name: str) -> set[str]:
    """Get column names for a table via information_schema (PostgreSQL)."""
    from sqlalchemy import text
    result = await conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        f"WHERE table_name = '{table_name}'"
    ))
    return {row[0] for row in result.fetchall()}


async def migrate_table(conn, table_name: str):
    from sqlalchemy import text
    existing = await get_existing_columns(conn, table_name)
    for col_name, col_def in NEW_COLUMNS:
        if col_name in existing:
            logger.info(f"  {table_name}.{col_name} — already exists, skipping")
            continue
        stmt = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}"
        await conn.execute(text(stmt))
        logger.info(f"  {table_name}.{col_name} — added")


async def main():
    async with async_engine.begin() as conn:
        logger.info("Migrating 'skills' table...")
        await migrate_table(conn, "skills")

        # Continuum version table
        from sqlalchemy import text
        try:
            await conn.execute(text("SELECT 1 FROM skills_version LIMIT 1"))
            logger.info("Migrating 'skills_version' table...")
            await migrate_table(conn, "skills_version")
        except Exception:
            logger.info("No 'skills_version' table found, skipping")

    logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())