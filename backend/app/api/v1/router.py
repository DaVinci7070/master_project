from fastapi import APIRouter
from app.api.v1.endpoints import (
    templates,
    agents,
    skills,
    prompts,
    telemetry,
    topology,
    ab_tests,
    challenges,
    dashboard,
    system,
    events,
    shared_memory,
    executions,
    gap_plans,
    evolution,
    evaluation,
    settings,
)

api_router = APIRouter(prefix="/api/v1")

# Entity CRUD routers
api_router.include_router(templates.router)
api_router.include_router(agents.router)
api_router.include_router(skills.router)
api_router.include_router(prompts.router)

# Data and monitoring routers
api_router.include_router(telemetry.router)
api_router.include_router(topology.router)
api_router.include_router(ab_tests.router)

# Challenge and system routers
api_router.include_router(challenges.router)
api_router.include_router(dashboard.router)
api_router.include_router(system.router)
api_router.include_router(events.router)

# Execution History & Shared Memory
api_router.include_router(shared_memory.router)
api_router.include_router(executions.router)

# Gap Plan monitoring
api_router.include_router(gap_plans.router)

# Autonomous Evolution Loop (Sprint 1)
api_router.include_router(evolution.router)

# Evaluation Dashboard (Sprint 8)
api_router.include_router(evaluation.router)

# Runtime Settings (Modellvergleich)
api_router.include_router(settings.router)

