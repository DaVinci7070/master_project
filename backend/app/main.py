import logging
import structlog

# Load .env FIRST before anything else
from dotenv import load_dotenv
load_dotenv()

from app.core.logging import setup_logging

setup_logging()

from fastapi import FastAPI
from contextlib import asynccontextmanager

from app.api.v1.router import api_router
from app.dependencies.dependencies import async_engine
from app.models.sql.sql_models import Base
from app.middleware.telemetry_middleware import setup_telemetry, shutdown_telemetry

logger = logging.getLogger(__name__)

# Store telemetry provider for shutdown
_telemetry_provider = None


async def init_db():
    from sqlalchemy import inspect, text

    async with async_engine.begin() as conn:
        # Check if tables already exist
        def check_tables(connection):
            inspector = inspect(connection)
            return inspector.get_table_names()

        existing_tables = await conn.run_sync(check_tables)

        if existing_tables:
            logger.info(f"Database already initialized ({len(existing_tables)} tables)")
            # Auto-migrate: add SoK skill columns if missing
            if "skills" in existing_tables:
                await _migrate_skill_columns(conn)
            if "skill_build_attempts" in existing_tables:
                await _migrate_build_attempt_columns(conn)
            # Auto-create new tables that don't exist yet
            await conn.run_sync(
                lambda sync_conn: Base.metadata.create_all(sync_conn, checkfirst=True)
            )
        else:
            logger.info("Initializing database tables...")
            await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables initialized.")


async def _migrate_skill_columns(conn):
    """Add SoK skill columns to existing skills table if missing."""
    from sqlalchemy import text

    # Detect database dialect and get existing columns
    dialect = conn.dialect.name
    if dialect == "sqlite":
        result = await conn.execute(text("PRAGMA table_info(skills)"))
        existing = {row[1] for row in result.fetchall()}
    else:
        result = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'skills'"
        ))
        existing = {row[0] for row in result.fetchall()}

    new_columns = [
        ("skill_type", "VARCHAR(20) NOT NULL DEFAULT 'functional'"),
        ("applicability", "TEXT"),
        ("instructions", "TEXT"),
        ("termination", "TEXT"),
        ("interface", "JSON"),
        ("dependencies", "JSON"),
    ]

    for col_name, col_def in new_columns:
        if col_name not in existing:
            await conn.execute(text(f"ALTER TABLE skills ADD COLUMN {col_name} {col_def}"))
            logger.info(f"Migrated skills table: added column '{col_name}'")


async def _migrate_build_attempt_columns(conn):
    """Add feedback-history columns to skill_build_attempts table if missing."""
    from sqlalchemy import text

    dialect = conn.dialect.name
    if dialect == "sqlite":
        result = await conn.execute(text("PRAGMA table_info(skill_build_attempts)"))
        existing = {row[1] for row in result.fetchall()}
    else:
        result = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'skill_build_attempts'"
        ))
        existing = {row[0] for row in result.fetchall()}

    new_columns = [
        ("strategy_id", "VARCHAR(100)"),
        ("error_type_classified", "VARCHAR(50)"),
        ("lesson_learned", "TEXT"),
        ("related_attempt_ids", "JSON"),
    ]

    for col_name, col_def in new_columns:
        if col_name not in existing:
            await conn.execute(text(
                f"ALTER TABLE skill_build_attempts ADD COLUMN {col_name} {col_def}"
            ))
            logger.info(f"Migrated skill_build_attempts: added column '{col_name}'")


async def _backfill_skill_applicability():
    """One-time backfill: generate applicability via LLM for skills that lack it."""
    from sqlalchemy import select
    from app.dependencies.dependencies import AsyncSessionLocal
    from app.models.sql.versioned_models import Skill
    from app.core.llm_client import LLMClient

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Skill).where(Skill.applicability.is_(None))
        )
        skills = result.scalars().all()

        if not skills:
            return

        logger.info(f"Backfilling applicability for {len(skills)} skills...")
        client = LLMClient()

        for skill in skills:
            if skill.skill_type != "functional":
                skill.skill_type = "functional"
            try:
                code_snippet = (skill.code or "")[:3000]
                prompt = (
                    "Given this skill's name, description, and code, write a concise "
                    "applicability statement (1-2 sentences) describing WHEN and UNDER "
                    "WHAT CONDITIONS this skill should be selected.\n\n"
                    f"Skill name: {skill.name}\n"
                    f"Description: {skill.description or '(none)'}\n"
                    f"Code:\n{code_snippet}\n\n"
                    "Respond with ONLY the applicability statement."
                )
                response = await client.chat(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=200,
                )
                skill.applicability = response.content.strip()
                logger.info(f"  {skill.name}: applicability set")
            except Exception as e:
                logger.warning(f"  {skill.name}: LLM backfill failed: {e}")

        await session.commit()
        logger.info("Applicability backfill complete")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _telemetry_provider

    # Initialize database
    await init_db()

    # Initialize OpenTelemetry (DB-07)
    _telemetry_provider = setup_telemetry(
        app,
        service_name="lumari-backend",
        service_version="0.1.0",
        enable_console_export=True,  # TODO: Make configurable
    )
    logger.info("OpenTelemetry instrumentation initialized")

    # Backfill applicability for skills that don't have it yet
    await _backfill_skill_applicability()

    # Initialize Skill Registry (Hot-Reload) if enabled
    from app.core.config import settings
    if settings.hot_reload_enabled:
        from app.skills.runtime.registry import SkillRegistry
        from app.dependencies.dependencies import AsyncSessionLocal

        registry = SkillRegistry.get_instance()
        async with AsyncSessionLocal() as db:
            skill_count = await registry.initialize(db)
            logger.info(f"Skill registry initialized with {skill_count} skills")

        # Register rebuild callback for auto-rebuild flagged skills
        async def _on_skill_rebuild_needed(skill_id: str, skill_name: str, reason: str | None) -> None:
            logger.warning(
                f"REBUILD_NEEDED: skill '{skill_name}' (id={skill_id[:8]}...) "
                f"flagged for rebuild. Reason: {reason}"
            )

        registry.set_rebuild_callback(_on_skill_rebuild_needed)

    yield

    # Shutdown telemetry
    shutdown_telemetry(_telemetry_provider)
    logger.info("OpenTelemetry shutdown complete")

app = FastAPI(
    title="Lumari Report AI - Backend",
    description="Prototype backend for AI-powered report site reports",
    version="0.1.0",
    lifespan=lifespan  
)

from app.core.middleware import RequestIdMiddleware, RateLimitMiddleware, SecurityMiddleware
from app.core.ratelimit import MemoryRateLimitStorage

_shared_storage = MemoryRateLimitStorage()

app.add_middleware(RateLimitMiddleware, storage=_shared_storage)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(SecurityMiddleware, storage=_shared_storage)

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.core.exceptions import LumariError
from app.core.handlers import (
    validation_exception_handler,
    http_exception_handler,
    generic_exception_handler,
    lumari_exception_handler
)

app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(LumariError, lumari_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

@app.get("/health")
async def health():
    return {"status": "healthy"}

app.include_router(api_router)

