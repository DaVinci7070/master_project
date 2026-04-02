"""
API endpoints for dashboard metrics and trends.

Provides system health, improvement trends, and recent activity.
All metrics are runs-based (last N executions) per CONTEXT.md.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.dependencies.dependencies import get_db_session
from app.models.sql.telemetry_models import ExecutionTelemetry
from app.models.sql.ab_test_models import ABTest
from app.models.sql.versioned_models import Prompt, Skill, Agent

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
log = logging.getLogger(__name__)


# Response models
class HealthMetricsResponse(BaseModel):
    """System health metrics."""
    total_executions: int
    successful_executions: int
    failed_executions: int
    success_rate: float  # Percentage
    active_executions: int  # Currently running
    avg_latency_ms: Optional[float] = None
    error_rate: float  # Percentage
    last_execution_at: Optional[str] = None
    # Resource usage (simplified for now)
    active_agents: int
    active_skills: int
    active_prompts: int


class ImprovementTrendResponse(BaseModel):
    """Improvement trends over recent runs."""
    ab_tests_completed: int
    ab_tests_successful: int  # Improvements that won
    ab_test_win_rate: float  # Percentage
    prompts_evolved: int  # Prompts with children
    skills_created: int
    agents_added: int
    # Trend direction
    improvement_trend: str  # "improving", "stable", "declining"


class RecentExecutionSummary(BaseModel):
    """Summary of a recent execution."""
    id: str
    agent_id: str
    outcome: str
    latency_ms: Optional[float] = None
    started_at: str


class RecentActivityResponse(BaseModel):
    """Recent execution summaries."""
    executions: list[RecentExecutionSummary]
    total_recent: int  # Count in last N runs


class DashboardResponse(BaseModel):
    """Complete dashboard data."""
    health: HealthMetricsResponse
    trends: ImprovementTrendResponse
    recent: RecentActivityResponse


@router.get("/health", response_model=HealthMetricsResponse)
async def get_health(
    last_n: int = Query(100, ge=1, le=1000, description="Number of recent executions to analyze"),
    session: AsyncSession = Depends(get_db_session),
) -> HealthMetricsResponse:
    """
    Get system health metrics.

    Aggregates over last N executions (runs-based, not time-based).
    """
    log.info(f"Getting health metrics: last_n={last_n}")

    # Get recent executions
    stmt = (
        select(ExecutionTelemetry)
        .order_by(ExecutionTelemetry.started_at.desc())
        .limit(last_n)
    )
    result = await session.execute(stmt)
    executions = list(result.scalars().all())

    total = len(executions)
    successful = sum(1 for e in executions if e.outcome == "success")
    failed = sum(1 for e in executions if e.outcome == "error")

    success_rate = (successful / total * 100) if total > 0 else 0.0
    error_rate = (failed / total * 100) if total > 0 else 0.0

    # Latency (only completed)
    latencies = [e.latency_ms for e in executions if e.latency_ms is not None]
    avg_latency = sum(latencies) / len(latencies) if latencies else None

    # Active executions (no completed_at)
    active = sum(1 for e in executions if e.completed_at is None)

    # Last execution
    last_execution_at = executions[0].started_at.isoformat() if executions else None

    # Resource counts
    agent_count = await session.execute(
        select(func.count()).select_from(Agent).where(Agent.is_active == True)
    )
    skill_count = await session.execute(
        select(func.count()).select_from(Skill).where(Skill.is_active == True)
    )
    prompt_count = await session.execute(
        select(func.count()).select_from(Prompt).where(Prompt.is_active == True)
    )

    return HealthMetricsResponse(
        total_executions=total,
        successful_executions=successful,
        failed_executions=failed,
        success_rate=success_rate,
        active_executions=active,
        avg_latency_ms=avg_latency,
        error_rate=error_rate,
        last_execution_at=last_execution_at,
        active_agents=agent_count.scalar() or 0,
        active_skills=skill_count.scalar() or 0,
        active_prompts=prompt_count.scalar() or 0,
    )


@router.get("/trends", response_model=ImprovementTrendResponse)
async def get_trends(
    last_n: int = Query(50, ge=1, le=500, description="Number of recent A/B tests to analyze"),
    session: AsyncSession = Depends(get_db_session),
) -> ImprovementTrendResponse:
    """
    Get improvement trends.

    Shows A/B test wins, prompt evolution, skills created, agents added.
    """
    log.info(f"Getting improvement trends: last_n={last_n}")

    # Get recent A/B tests
    stmt = (
        select(ABTest)
        .order_by(ABTest.created_at.desc())
        .limit(last_n)
    )
    result = await session.execute(stmt)
    ab_tests = list(result.scalars().all())

    completed = [t for t in ab_tests if t.status == "completed"]
    successful = [t for t in completed if t.is_significant == 1]

    ab_win_rate = (len(successful) / len(completed) * 100) if completed else 0.0

    # Prompts evolved (those with children)
    prompt_stmt = select(func.count(func.distinct(Prompt.parent_id))).where(Prompt.parent_id.isnot(None))
    prompts_evolved_result = await session.execute(prompt_stmt)
    prompts_evolved = prompts_evolved_result.scalar() or 0

    # Skills created (count all skills)
    skill_count = await session.execute(select(func.count()).select_from(Skill))
    skills_created = skill_count.scalar() or 0

    # Agents added (count all agents)
    agent_count = await session.execute(select(func.count()).select_from(Agent))
    agents_added = agent_count.scalar() or 0

    # Determine trend
    if len(successful) > len(completed) / 2 and len(completed) > 3:
        improvement_trend = "improving"
    elif len(successful) < len(completed) / 4 and len(completed) > 3:
        improvement_trend = "declining"
    else:
        improvement_trend = "stable"

    return ImprovementTrendResponse(
        ab_tests_completed=len(completed),
        ab_tests_successful=len(successful),
        ab_test_win_rate=ab_win_rate,
        prompts_evolved=prompts_evolved,
        skills_created=skills_created,
        agents_added=agents_added,
        improvement_trend=improvement_trend,
    )


@router.get("/recent", response_model=RecentActivityResponse)
async def get_recent(
    limit: int = Query(20, ge=1, le=100, description="Number of recent executions"),
    session: AsyncSession = Depends(get_db_session),
) -> RecentActivityResponse:
    """
    Get recent execution summaries.

    Returns the most recent executions for activity monitoring.
    """
    log.info(f"Getting recent activity: limit={limit}")

    stmt = (
        select(ExecutionTelemetry)
        .order_by(ExecutionTelemetry.started_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    executions = list(result.scalars().all())

    return RecentActivityResponse(
        executions=[
            RecentExecutionSummary(
                id=e.id,
                agent_id=e.agent_id,
                outcome=e.outcome,
                latency_ms=e.latency_ms,
                started_at=e.started_at.isoformat() if e.started_at else "",
            )
            for e in executions
        ],
        total_recent=len(executions),
    )


@router.get("", response_model=DashboardResponse)
async def get_dashboard(
    session: AsyncSession = Depends(get_db_session),
) -> DashboardResponse:
    """
    Get complete dashboard data.

    Combines health, trends, and recent activity in one response.
    """
    log.info("Getting complete dashboard")

    # Call each sub-endpoint
    health = await get_health(last_n=100, session=session)
    trends = await get_trends(last_n=50, session=session)
    recent = await get_recent(limit=10, session=session)

    return DashboardResponse(
        health=health,
        trends=trends,
        recent=recent,
    )
