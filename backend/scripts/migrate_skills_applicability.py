"""
Migration script: Backfill skill_type and applicability for existing skills.

For each skill where applicability is NULL:
  1. Sets skill_type = "functional"
  2. Generates applicability via LLM call from description + code

Usage:
    python scripts/migrate_skills_applicability.py
    python scripts/migrate_skills_applicability.py --dry-run
"""
import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select, text
from app.dependencies.dependencies import async_engine, AsyncSessionLocal
from app.models.sql.versioned_models import Skill
from app.core.llm_client import LLMClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

APPLICABILITY_PROMPT = """\
Given this skill's name, description, and code, write a concise applicability statement \
(1-2 sentences) describing WHEN and UNDER WHAT CONDITIONS this skill should be selected. \
Focus on the input characteristics and task types that make this skill the right choice.

Skill name: {name}
Description: {description}
Code:
{code}

Respond with ONLY the applicability statement, nothing else."""


async def generate_applicability(client: LLMClient, skill: Skill) -> str:
    """Generate an applicability statement for a skill via LLM."""
    code_snippet = (skill.code or "")[:3000]  # truncate to avoid token limits
    prompt = APPLICABILITY_PROMPT.format(
        name=skill.name,
        description=skill.description or "(no description)",
        code=code_snippet,
    )
    response = await client.chat(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=200,
    )
    return response.content.strip()


async def main():
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        logger.info("DRY RUN — no changes will be written")

    client = LLMClient()
    migrated = 0
    skipped = 0
    errors = 0

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Skill))
        skills = result.scalars().all()

        logger.info(f"Found {len(skills)} skills total")

        for skill in skills:
            # Skip skills that already have applicability
            if skill.applicability:
                skipped += 1
                continue

            logger.info(f"Processing: {skill.name} (id={skill.id})")

            # Set skill_type
            if skill.skill_type != "functional":
                skill.skill_type = "functional"

            # Generate applicability via LLM
            try:
                applicability = await generate_applicability(client, skill)
                logger.info(f"  -> applicability: {applicability[:100]}...")

                if not dry_run:
                    skill.applicability = applicability

                migrated += 1
            except Exception as e:
                logger.error(f"  LLM error for {skill.name}: {e}")
                errors += 1

        if not dry_run:
            await session.commit()
            logger.info("Changes committed to database")

    logger.info(f"Done. Migrated: {migrated}, Skipped: {skipped}, Errors: {errors}")


if __name__ == "__main__":
    asyncio.run(main())
