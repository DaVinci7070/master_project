from fastapi import APIRouter
from app.api.v1.endpoints import (
    transcripts,
    reports,
    templates,
    assistant,
    orchestration,
    # Phase 11 - Frontend API endpoints
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
    # Phase 12 - Execution History & Shared Memory
    shared_memory,
    executions,
    # Gap Plan monitoring
    gap_plans,
)

api_router = APIRouter(prefix="/api/v1")

# Existing routers
api_router.include_router(transcripts.router)
api_router.include_router(reports.router)
api_router.include_router(templates.router)
api_router.include_router(assistant.router)
api_router.include_router(orchestration.router)

# Phase 11 - Entity CRUD routers
api_router.include_router(agents.router)
api_router.include_router(skills.router)
api_router.include_router(prompts.router)

# Phase 11 - Data and monitoring routers
api_router.include_router(telemetry.router)
api_router.include_router(topology.router)
api_router.include_router(ab_tests.router)

# Phase 11 - Challenge and system routers
api_router.include_router(challenges.router)
api_router.include_router(dashboard.router)
api_router.include_router(system.router)
api_router.include_router(events.router)

# Phase 12 - Execution History & Shared Memory
api_router.include_router(shared_memory.router)
api_router.include_router(executions.router)

# Gap Plan monitoring
api_router.include_router(gap_plans.router)

