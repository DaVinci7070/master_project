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
    from sqlalchemy import inspect

    async with async_engine.begin() as conn:
        # Check if tables already exist
        def check_tables(connection):
            inspector = inspect(connection)
            return inspector.get_table_names()

        existing_tables = await conn.run_sync(check_tables)

        if existing_tables:
            logger.info(f"Database already initialized ({len(existing_tables)} tables)")
        else:
            logger.info("Initializing database tables...")
            await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables initialized.")


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

    # Initialize Skill Registry (Hot-Reload) if enabled
    from app.core.config import settings
    if settings.hot_reload_enabled:
        from app.services.skill_registry import SkillRegistry
        from app.dependencies.dependencies import AsyncSessionLocal

        registry = SkillRegistry.get_instance()
        async with AsyncSessionLocal() as db:
            skill_count = await registry.initialize(db)
            logger.info(f"Skill registry initialized with {skill_count} skills")

    yield

    # Shutdown telemetry
    shutdown_telemetry(_telemetry_provider)
    logger.info("OpenTelemetry shutdown complete")

    # Close orchestrator client
    from app.dependencies.dependencies import get_orchestrator_adapter
    orchestrator = get_orchestrator_adapter()
    await orchestrator.close()
    logger.info("Closed orchestrator HTTP client")

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

