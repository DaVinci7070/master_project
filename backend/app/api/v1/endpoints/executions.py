"""
API endpoints for Execution History.

Provides access to persisted execution records for history view.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.dependencies.dependencies import get_db_session
from app.models.sql.execution_models import Execution
from app.models.sql.agent_event_models import AgentExecutionEvent

router = APIRouter(prefix="/executions", tags=["executions"])
log = logging.getLogger(__name__)


@router.get("")
async def list_executions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None, description="Filter by status: pending, running, completed, failed"),
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    List all executions with pagination.

    Returns execution history sorted by start time (most recent first).
    """
    log.info(f"Listing executions: limit={limit}, offset={offset}, status={status}")

    executions = []
    total = 0

    try:
        stmt = select(Execution).order_by(desc(Execution.started_at))

        if status:
            stmt = stmt.where(Execution.status == status)
        if project_id:
            stmt = stmt.where(Execution.project_id == project_id)

        stmt = stmt.limit(limit).offset(offset)

        result = await session.execute(stmt)
        executions = list(result.scalars().all())

        # Get total count
        count_stmt = select(Execution)
        if status:
            count_stmt = count_stmt.where(Execution.status == status)
        if project_id:
            count_stmt = count_stmt.where(Execution.project_id == project_id)

        count_result = await session.execute(count_stmt)
        total = len(list(count_result.scalars().all()))
    except Exception as e:
        log.warning(f"Failed to list executions (table may not exist): {e}")
        try:
            await session.rollback()
        except Exception:
            pass

    return {
        "executions": [
            {
                "id": e.id,
                "challenge_id": e.challenge_id,
                "project_id": e.project_id,
                "status": e.status,
                "agents_executed": e.agents_executed,
                "waves_executed": e.waves_executed,
                "duration_ms": e.duration_ms,
                "error": e.error,
                "started_at": e.started_at.isoformat() if e.started_at else None,
                "completed_at": e.completed_at.isoformat() if e.completed_at else None,
            }
            for e in executions
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{execution_id}")
async def get_execution(
    execution_id: str,
    include_events: bool = Query(False, description="Include agent execution events"),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Get full details for a single execution.

    Includes results, input data, and optionally agent events.
    """
    log.info(f"Getting execution: {execution_id}")

    try:
        stmt = select(Execution).where(Execution.id == execution_id)
        result = await session.execute(stmt)
        execution = result.scalar_one_or_none()

        if not execution:
            raise HTTPException(status_code=404, detail="Execution not found")

        response = {
            "id": execution.id,
            "challenge_id": execution.challenge_id,
            "project_id": execution.project_id,
            "status": execution.status,
            "input_data": execution.input_data,
            "results": execution.results,
            "agents_executed": execution.agents_executed,
            "waves_executed": execution.waves_executed,
            "duration_ms": execution.duration_ms,
            "error": execution.error,
            "started_at": execution.started_at.isoformat() if execution.started_at else None,
            "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
        }

        if include_events:
            try:
                events_stmt = select(AgentExecutionEvent).where(
                    AgentExecutionEvent.execution_id == execution_id
                ).order_by(AgentExecutionEvent.created_at.asc())

                events_result = await session.execute(events_stmt)
                events = list(events_result.scalars().all())

                response["events"] = [
                    {
                        "id": e.id,
                        "agent_id": e.agent_id,
                        "agent_name": e.agent_name,
                        "event_type": e.event_type,
                        "wave": e.wave,
                        "data": e.data,
                        "error": e.error,
                        "created_at": e.created_at.isoformat() if e.created_at else None,
                    }
                    for e in events
                ]
            except Exception as e:
                log.warning(f"Failed to fetch events: {e}")
                response["events"] = []

        return response
    except HTTPException:
        raise
    except Exception as e:
        log.warning(f"Failed to get execution (table may not exist): {e}")
        raise HTTPException(status_code=404, detail="Execution not found or table does not exist")


@router.get("/{execution_id}/events")
async def get_execution_events(
    execution_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Get all agent events for an execution.

    Returns timeline events for agent start/complete/error.
    """
    events = []

    try:
        stmt = select(AgentExecutionEvent).where(
            AgentExecutionEvent.execution_id == execution_id
        ).order_by(AgentExecutionEvent.created_at.asc())

        result = await session.execute(stmt)
        events = list(result.scalars().all())
    except Exception as e:
        log.warning(f"Failed to fetch events (table may not exist): {e}")
        try:
            await session.rollback()
        except Exception:
            pass

    return {
        "execution_id": execution_id,
        "total": len(events),
        "events": [
            {
                "id": e.id,
                "agent_id": e.agent_id,
                "agent_name": e.agent_name,
                "event_type": e.event_type,
                "wave": e.wave,
                "data": e.data,
                "error": e.error,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }
