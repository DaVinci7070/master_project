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

api_router.include_router(templates.router)
api_router.include_router(agents.router)
api_router.include_router(skills.router)
api_router.include_router(prompts.router)

api_router.include_router(telemetry.router)
api_router.include_router(topology.router)
api_router.include_router(ab_tests.router)

api_router.include_router(challenges.router)
api_router.include_router(dashboard.router)
api_router.include_router(system.router)
api_router.include_router(events.router)

api_router.include_router(shared_memory.router)
api_router.include_router(executions.router)

api_router.include_router(gap_plans.router)

api_router.include_router(evolution.router)

api_router.include_router(evaluation.router)

api_router.include_router(settings.router)
