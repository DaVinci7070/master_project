"""
Migration script: Add feedback-history columns to skill_build_attempts table.

Adds: strategy_id, error_type_classified, lesson_learned, related_attempt_ids

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

NEW_COLUMNS = [
    ("strategy_id", "VARCHAR(100)"),
    ("error_type_classified", "VARCHAR(50)"),
    ("lesson_learned", "TEXT"),
    ("related_attempt_ids", "JSON"),
]


async def get_existing_columns(conn, table_name: str) -> set[str]:
    from sqlalchemy import text
    try:
        result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
        return {row[1] for row in result.fetchall()}
    except Exception:
        result = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{table_name}'"
        ))
        return {row[0] for row in result.fetchall()}


async def main():
    async with async_engine.begin() as conn:
        from sqlalchemy import text
        existing = await get_existing_columns(conn, "skill_build_attempts")

        for col_name, col_def in NEW_COLUMNS:
            if col_name in existing:
                logger.info(f"  {col_name} — already exists, skipping")
                continue
            await conn.execute(text(
                f"ALTER TABLE skill_build_attempts ADD COLUMN {col_name} {col_def}"
            ))
            logger.info(f"  {col_name} — added")

    logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
