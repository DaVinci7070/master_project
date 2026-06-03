import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.dependencies.dependencies import get_db_session
from app.repositories.telemetry_repository import TelemetryRepository
from app.models.sql.telemetry_models import ExecutionTelemetry

router = APIRouter(prefix="/telemetry", tags=["telemetry"])
log = logging.getLogger(__name__)


class ExecutionSummaryResponse(BaseModel):
    """Summary of an execution run."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_id: str
    execution_id: str
    outcome: str
    latency_ms: Optional[float] = None
    tokens_total: int = 0
    started_at: str
    completed_at: Optional[str] = None


class ExecutionDetailResponse(BaseModel):
    """Detailed execution run with all steps and metadata."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_id: str
    execution_id: str
    outcome: str
    latency_ms: Optional[float] = None
    tokens_input: int = 0
    tokens_output: int = 0
    tokens_total: int = 0
    input_hash: str
    output_hash: Optional[str] = None
    error_message: Optional[str] = None
    error_type: Optional[str] = None
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    execution_metadata: dict = Field(default_factory=dict)
    started_at: str
    completed_at: Optional[str] = None


class ExecutionListResponse(BaseModel):
    """Paginated execution list response."""
    executions: list[ExecutionSummaryResponse]
    total: int
    limit: int
    offset: int


class MetricsSummaryResponse(BaseModel):
    """Aggregated metrics for executions."""
    total_executions: int
    successful_executions: int
    failed_executions: int
    success_rate: float
    avg_latency_ms: Optional[float] = None
    min_latency_ms: Optional[float] = None
    max_latency_ms: Optional[float] = None
    total_tokens: int = 0
    avg_tokens_per_execution: Optional[float] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None


class AgentTelemetryResponse(BaseModel):
    """Aggregated telemetry for a specific agent."""
    agent_id: str
    total_executions: int
    successful_executions: int
    failed_executions: int
    timeout_executions: int
    cancelled_executions: int
    success_rate: float
    avg_latency_ms: Optional[float] = None
    min_latency_ms: Optional[float] = None
    max_latency_ms: Optional[float] = None
    p50_latency_ms: Optional[float] = None
    p95_latency_ms: Optional[float] = None
    p99_latency_ms: Optional[float] = None
    total_tokens_input: int = 0
    total_tokens_output: int = 0
    total_tokens: int = 0
    avg_tokens_per_execution: Optional[float] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None


@router.get("/executions", response_model=ExecutionListResponse)
async def list_executions(
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    outcome: Optional[str] = Query(None, description="Filter by outcome: success, error, timeout"),
    limit: int = Query(100, ge=1, le=500, description="Max results (default 100)"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    session: AsyncSession = Depends(get_db_session),
) -> ExecutionListResponse:
    """
    List execution runs with pagination.

    Supports filtering by agent and outcome.
    """
    log.info(f"Listing executions: agent_id={agent_id}, outcome={outcome}, limit={limit}, offset={offset}")

    stmt = select(ExecutionTelemetry).order_by(ExecutionTelemetry.started_at.desc())

    if agent_id:
        stmt = stmt.where(ExecutionTelemetry.agent_id == agent_id)

    if outcome:
        stmt = stmt.where(ExecutionTelemetry.outcome == outcome)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0

    stmt = stmt.limit(limit).offset(offset)

    result = await session.execute(stmt)
    executions = list(result.scalars().all())

    return ExecutionListResponse(
        executions=[
            ExecutionSummaryResponse(
                id=e.id,
                agent_id=e.agent_id,
                execution_id=e.execution_id,
                outcome=e.outcome,
                latency_ms=e.latency_ms,
                tokens_total=e.tokens_total or 0,
                started_at=e.started_at.isoformat() if e.started_at else "",
                completed_at=e.completed_at.isoformat() if e.completed_at else None,
            )
            for e in executions
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/executions/{execution_id}", response_model=ExecutionDetailResponse)
async def get_execution(
    execution_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> ExecutionDetailResponse:
    """
    Get execution detail with all steps and metadata.

    Returns 404 if execution not found.
    """
    log.info(f"Getting execution: id={execution_id}")

    repo = TelemetryRepository(session)
    execution = await repo.get_by_execution_id(execution_id)

    if not execution:
        execution = await repo.get_by_id(execution_id)

    if not execution:
        raise HTTPException(status_code=404, detail=f"Execution not found: {execution_id}")

    return ExecutionDetailResponse(
        id=execution.id,
        agent_id=execution.agent_id,
        execution_id=execution.execution_id,
        outcome=execution.outcome,
        latency_ms=execution.latency_ms,
        tokens_input=execution.tokens_input or 0,
        tokens_output=execution.tokens_output or 0,
        tokens_total=execution.tokens_total or 0,
        input_hash=execution.input_hash,
        output_hash=execution.output_hash,
        error_message=execution.error_message,
        error_type=execution.error_type,
        trace_id=execution.trace_id,
        span_id=execution.span_id,
        execution_metadata=execution.execution_metadata or {},
        started_at=execution.started_at.isoformat() if execution.started_at else "",
        completed_at=execution.completed_at.isoformat() if execution.completed_at else None,
    )


@router.get("/metrics", response_model=MetricsSummaryResponse)
async def get_metrics(
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    last_n: int = Query(100, ge=1, le=1000, description="Number of recent executions to aggregate"),
    session: AsyncSession = Depends(get_db_session),
) -> MetricsSummaryResponse:
    """
    Get aggregated metrics for executions.

    Aggregates over the last N executions (default 100).
    Runs-based aggregation per CONTEXT.md dashboard requirement.
    """
    log.info(f"Getting metrics: agent_id={agent_id}, last_n={last_n}")

    stmt = (
        select(ExecutionTelemetry)
        .order_by(ExecutionTelemetry.started_at.desc())
        .limit(last_n)
    )

    if agent_id:
        stmt = stmt.where(ExecutionTelemetry.agent_id == agent_id)

    result = await session.execute(stmt)
    executions = list(result.scalars().all())

    if not executions:
        return MetricsSummaryResponse(
            total_executions=0,
            successful_executions=0,
            failed_executions=0,
            success_rate=0.0,
        )

    total = len(executions)
    successful = sum(1 for e in executions if e.outcome == "success")
    failed = sum(1 for e in executions if e.outcome == "error")

    success_rate = (successful / total * 100) if total > 0 else 0.0

    latencies = [e.latency_ms for e in executions if e.latency_ms is not None]
    avg_latency = sum(latencies) / len(latencies) if latencies else None
    min_latency = min(latencies) if latencies else None
    max_latency = max(latencies) if latencies else None

    total_tokens = sum(e.tokens_total or 0 for e in executions)
    avg_tokens = total_tokens / total if total > 0 else None

    period_start = min(e.started_at for e in executions) if executions else None
    period_end = max(e.started_at for e in executions) if executions else None

    return MetricsSummaryResponse(
        total_executions=total,
        successful_executions=successful,
        failed_executions=failed,
        success_rate=success_rate,
        avg_latency_ms=avg_latency,
        min_latency_ms=min_latency,
        max_latency_ms=max_latency,
        total_tokens=total_tokens,
        avg_tokens_per_execution=avg_tokens,
        period_start=period_start.isoformat() if period_start else None,
        period_end=period_end.isoformat() if period_end else None,
    )


@router.get("/agents/{agent_id}", response_model=AgentTelemetryResponse)
async def get_agent_telemetry(
    agent_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> AgentTelemetryResponse:
    """
    Get aggregated telemetry for a specific agent.

    Returns execution stats, latency percentiles, and token usage.
    """
    log.info(f"Getting agent telemetry: agent_id={agent_id}")

    stmt = (
        select(ExecutionTelemetry)
        .where(ExecutionTelemetry.agent_id == agent_id)
        .order_by(ExecutionTelemetry.started_at.desc())
    )
    result = await session.execute(stmt)
    executions = list(result.scalars().all())

    total = len(executions)
    if total == 0:
        return AgentTelemetryResponse(
            agent_id=agent_id,
            total_executions=0,
            successful_executions=0,
            failed_executions=0,
            timeout_executions=0,
            cancelled_executions=0,
            success_rate=0.0,
        )

    successful = sum(1 for e in executions if e.outcome == "success")
    failed = sum(1 for e in executions if e.outcome == "error")
    timeout = sum(1 for e in executions if e.outcome == "timeout")
    cancelled = sum(1 for e in executions if e.outcome == "cancelled")

    latencies = sorted([e.latency_ms for e in executions if e.latency_ms is not None])
    avg_latency = sum(latencies) / len(latencies) if latencies else None
    min_latency = latencies[0] if latencies else None
    max_latency = latencies[-1] if latencies else None

    def percentile(sorted_vals: list[float], p: float) -> Optional[float]:
        if not sorted_vals:
            return None
        idx = int(len(sorted_vals) * p / 100)
        return sorted_vals[min(idx, len(sorted_vals) - 1)]

    total_tokens_input = sum(e.tokens_input or 0 for e in executions)
    total_tokens_output = sum(e.tokens_output or 0 for e in executions)
    total_tokens = sum(e.tokens_total or 0 for e in executions)

    period_start = min(e.started_at for e in executions)
    period_end = max(e.started_at for e in executions)

    return AgentTelemetryResponse(
        agent_id=agent_id,
        total_executions=total,
        successful_executions=successful,
        failed_executions=failed,
        timeout_executions=timeout,
        cancelled_executions=cancelled,
        success_rate=(successful / total * 100) if total > 0 else 0.0,
        avg_latency_ms=avg_latency,
        min_latency_ms=min_latency,
        max_latency_ms=max_latency,
        p50_latency_ms=percentile(latencies, 50),
        p95_latency_ms=percentile(latencies, 95),
        p99_latency_ms=percentile(latencies, 99),
        total_tokens_input=total_tokens_input,
        total_tokens_output=total_tokens_output,
        total_tokens=total_tokens,
        avg_tokens_per_execution=total_tokens / total if total > 0 else None,
        period_start=period_start.isoformat() if period_start else None,
        period_end=period_end.isoformat() if period_end else None,
    )


class TelemetrySummaryResponse(BaseModel):
    """Dashboard summary stats for telemetry."""
    total_executions: int
    executions_last_hour: int
    executions_last_24h: int
    success_rate_overall: float
    success_rate_last_hour: Optional[float] = None
    avg_latency_ms: Optional[float] = None
    avg_latency_last_hour: Optional[float] = None
    total_tokens_consumed: int
    tokens_last_hour: int
    unique_agents: int
    most_active_agent_id: Optional[str] = None
    last_execution_at: Optional[str] = None


@router.get("/summary", response_model=TelemetrySummaryResponse)
async def get_telemetry_summary(
    session: AsyncSession = Depends(get_db_session),
) -> TelemetrySummaryResponse:
    """
    Get dashboard summary statistics for telemetry.

    Returns aggregated metrics for the system health dashboard.
    """
    log.info("Getting telemetry summary")

    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    one_day_ago = now - timedelta(hours=24)

    total_stmt = select(func.count()).select_from(ExecutionTelemetry)
    total_result = await session.execute(total_stmt)
    total_executions = total_result.scalar() or 0

    hour_stmt = select(func.count()).select_from(ExecutionTelemetry).where(
        ExecutionTelemetry.started_at >= one_hour_ago
    )
    hour_result = await session.execute(hour_stmt)
    executions_last_hour = hour_result.scalar() or 0

    day_stmt = select(func.count()).select_from(ExecutionTelemetry).where(
        ExecutionTelemetry.started_at >= one_day_ago
    )
    day_result = await session.execute(day_stmt)
    executions_last_24h = day_result.scalar() or 0

    success_stmt = select(func.count()).select_from(ExecutionTelemetry).where(
        ExecutionTelemetry.outcome == "success"
    )
    success_result = await session.execute(success_stmt)
    successful = success_result.scalar() or 0
    success_rate_overall = (successful / total_executions * 100) if total_executions > 0 else 0.0

    success_hour_stmt = select(func.count()).select_from(ExecutionTelemetry).where(
        ExecutionTelemetry.outcome == "success",
        ExecutionTelemetry.started_at >= one_hour_ago
    )
    success_hour_result = await session.execute(success_hour_stmt)
    successful_hour = success_hour_result.scalar() or 0
    success_rate_last_hour = (successful_hour / executions_last_hour * 100) if executions_last_hour > 0 else None

    avg_latency_stmt = select(func.avg(ExecutionTelemetry.latency_ms)).where(
        ExecutionTelemetry.latency_ms.isnot(None)
    )
    avg_latency_result = await session.execute(avg_latency_stmt)
    avg_latency_ms = avg_latency_result.scalar()

    avg_latency_hour_stmt = select(func.avg(ExecutionTelemetry.latency_ms)).where(
        ExecutionTelemetry.latency_ms.isnot(None),
        ExecutionTelemetry.started_at >= one_hour_ago
    )
    avg_latency_hour_result = await session.execute(avg_latency_hour_stmt)
    avg_latency_last_hour = avg_latency_hour_result.scalar()

    tokens_stmt = select(func.sum(ExecutionTelemetry.tokens_total))
    tokens_result = await session.execute(tokens_stmt)
    total_tokens_consumed = tokens_result.scalar() or 0

    tokens_hour_stmt = select(func.sum(ExecutionTelemetry.tokens_total)).where(
        ExecutionTelemetry.started_at >= one_hour_ago
    )
    tokens_hour_result = await session.execute(tokens_hour_stmt)
    tokens_last_hour = tokens_hour_result.scalar() or 0

    unique_agents_stmt = select(func.count(func.distinct(ExecutionTelemetry.agent_id)))
    unique_agents_result = await session.execute(unique_agents_stmt)
    unique_agents = unique_agents_result.scalar() or 0

    most_active_stmt = (
        select(ExecutionTelemetry.agent_id, func.count().label("count"))
        .group_by(ExecutionTelemetry.agent_id)
        .order_by(func.count().desc())
        .limit(1)
    )
    most_active_result = await session.execute(most_active_stmt)
    most_active_row = most_active_result.first()
    most_active_agent_id = most_active_row[0] if most_active_row else None

    last_exec_stmt = select(ExecutionTelemetry.started_at).order_by(
        ExecutionTelemetry.started_at.desc()
    ).limit(1)
    last_exec_result = await session.execute(last_exec_stmt)
    last_exec = last_exec_result.scalar()
    last_execution_at = last_exec.isoformat() if last_exec else None

    return TelemetrySummaryResponse(
        total_executions=total_executions,
        executions_last_hour=executions_last_hour,
        executions_last_24h=executions_last_24h,
        success_rate_overall=success_rate_overall,
        success_rate_last_hour=success_rate_last_hour,
        avg_latency_ms=float(avg_latency_ms) if avg_latency_ms else None,
        avg_latency_last_hour=float(avg_latency_last_hour) if avg_latency_last_hour else None,
        total_tokens_consumed=total_tokens_consumed,
        tokens_last_hour=tokens_last_hour,
        unique_agents=unique_agents,
        most_active_agent_id=most_active_agent_id,
        last_execution_at=last_execution_at,
    )
