"""
Evolution API Endpoints (Sprint 1).

- POST /evolution/executions/{id}/evolve  — manual trigger (debug/demo/evaluation)
- GET  /evolution/history                 — chronological evolution.* events
- GET  /evolution/stats                   — aggregated improvement stats
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.dependencies import get_db_session
from app.dependencies.evolution_loop import get_evolution_loop_service
from app.models.schemas.evolution_schemas import EvolutionReport
from app.models.sql.agent_event_models import AgentExecutionEvent
from app.models.sql.improvement_models import ImprovementAttempt
from app.services.evolution_loop_service import EvolutionLoopService

router = APIRouter(prefix="/evolution", tags=["evolution"])


@router.post(
    "/executions/{execution_id}/evolve",
    response_model=EvolutionReport,
)
async def trigger_evolution(
    execution_id: str,
    service: EvolutionLoopService = Depends(get_evolution_loop_service),
) -> EvolutionReport:
    """Manually trigger the evolution loop for a given execution."""
    return await service.run_post_execution_evolution(execution_id)


@router.get("/history")
async def evolution_history(
    execution_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Chronological evolution.* events, optionally filtered by execution_id."""
    stmt = select(AgentExecutionEvent).where(
        AgentExecutionEvent.event_type.like("evolution.%")
    )
    if execution_id:
        stmt = stmt.where(AgentExecutionEvent.execution_id == execution_id)
    stmt = stmt.order_by(AgentExecutionEvent.created_at.asc()).limit(limit)

    result = await db.execute(stmt)
    events = list(result.scalars().all())
    return {
        "execution_id": execution_id,
        "count": len(events),
        "events": [
            {
                "id": e.id,
                "execution_id": e.execution_id,
                "event_type": e.event_type,
                "agent_id": e.agent_id,
                "data": e.data,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }


@router.get("/stats")
async def evolution_stats(
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Aggregate improvement stats: attempted, succeeded, failed, rolled-back."""
    result = await db.execute(select(ImprovementAttempt))
    attempts = list(result.scalars().all())

    by_status: dict[str, int] = {}
    by_artifact: dict[str, int] = {}
    for a in attempts:
        by_status[a.status] = by_status.get(a.status, 0) + 1
        by_artifact[a.artifact_type] = by_artifact.get(a.artifact_type, 0) + 1

    return {
        "total_attempts": len(attempts),
        "by_status": by_status,
        "by_artifact_type": by_artifact,
    }