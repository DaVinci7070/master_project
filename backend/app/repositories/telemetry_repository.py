"""
Telemetry repository for execution telemetry data access.

This module implements DB-07 (execution telemetry) and DB-08 (input/output hashing)
storage operations. ExecutionTelemetry records are append-only for audit trail.
"""
import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sql.telemetry_models import ExecutionTelemetry
from app.models.schemas.telemetry_schemas import (
    ExecutionTelemetryCreate,
    ExecutionTelemetryUpdate,
    TelemetryAggregation,
)

log = logging.getLogger(__name__)


def compute_hash(data: Any) -> str:
    """
    Compute SHA-256 hash of input data, truncated to 64 characters.

    This function implements DB-08 requirement for input/output hashing.
    It normalizes data to JSON before hashing for consistent results.

    Args:
        data: Any data that can be serialized to JSON.
              Dicts, lists, strings, numbers, booleans, None are supported.

    Returns:
        64-character hex string (full SHA-256 hash).

    Examples:
        >>> compute_hash({"test": "data"})
        'a238e69b7a3c9f1c3d92d3...'  # 64 chars
        >>> compute_hash("simple string")
        '9f86d081884c7d659a2fea...'
    """
    # Normalize to JSON with sorted keys for consistent hashing
    if isinstance(data, str):
        # If already a string, use as-is
        normalized = data
    else:
        # Serialize to JSON with sorted keys for deterministic output
        normalized = json.dumps(data, sort_keys=True, separators=(',', ':'))

    # Compute SHA-256 hash
    hash_bytes = hashlib.sha256(normalized.encode('utf-8')).hexdigest()

    # Return full 64-character hash (SHA-256 produces 64 hex chars)
    return hash_bytes[:64]


class TelemetryRepository:
    """
    Repository for ExecutionTelemetry database operations.

    This repository follows append-only pattern for audit trail compliance.
    Records are never deleted, only created or updated to completion state.

    All operations are async for non-blocking database access.
    """

    def __init__(self, session: AsyncSession):
        """
        Initialize repository with database session.

        Args:
            session: SQLAlchemy async session for database operations.
        """
        self.session = session

    async def create(self, telemetry: ExecutionTelemetryCreate) -> ExecutionTelemetry:
        """
        Create a new telemetry record (append-only).

        This is called when an agent execution starts. The record is created
        with initial data and later updated when execution completes.

        Args:
            telemetry: Validated creation schema with required fields.

        Returns:
            Created ExecutionTelemetry database model.
        """
        log.info(
            f"Creating telemetry record for agent={telemetry.agent_id[:8]}..., "
            f"execution={telemetry.execution_id[:8]}..."
        )

        db_telemetry = ExecutionTelemetry(
            agent_id=telemetry.agent_id,
            execution_id=telemetry.execution_id,
            started_at=telemetry.started_at,
            input_hash=telemetry.input_hash,
            outcome=telemetry.outcome,
            trace_id=telemetry.trace_id,
            span_id=telemetry.span_id,
            execution_metadata=telemetry.execution_metadata or {},
        )

        self.session.add(db_telemetry)
        await self.session.commit()
        await self.session.refresh(db_telemetry)

        log.info(f"Created telemetry record id={db_telemetry.id}")
        return db_telemetry

    async def update(
        self, telemetry_id: str, update_data: ExecutionTelemetryUpdate
    ) -> Optional[ExecutionTelemetry]:
        """
        Update a telemetry record when execution completes.

        This updates completion fields like latency_ms, output_hash,
        tokens consumed, and final outcome.

        Args:
            telemetry_id: UUID of the telemetry record to update.
            update_data: Validated update schema with completion data.

        Returns:
            Updated ExecutionTelemetry or None if not found.
        """
        log.info(f"Updating telemetry record id={telemetry_id}")

        record = await self.get_by_id(telemetry_id)
        if not record:
            log.warning(f"Telemetry record not found: {telemetry_id}")
            return None

        # Update only provided fields
        update_dict = update_data.model_dump(exclude_none=True)
        for field, value in update_dict.items():
            setattr(record, field, value)

        await self.session.commit()
        await self.session.refresh(record)

        log.info(f"Updated telemetry record id={telemetry_id}, outcome={record.outcome}")
        return record

    async def get_by_id(self, telemetry_id: str) -> Optional[ExecutionTelemetry]:
        """
        Get a telemetry record by its ID.

        Args:
            telemetry_id: UUID of the telemetry record.

        Returns:
            ExecutionTelemetry or None if not found.
        """
        stmt = select(ExecutionTelemetry).where(ExecutionTelemetry.id == telemetry_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_execution_id(
        self, execution_id: str
    ) -> Optional[ExecutionTelemetry]:
        """
        Get telemetry record by execution ID.

        An execution_id uniquely identifies a single agent run,
        so this returns at most one record.

        Args:
            execution_id: UUID of the execution.

        Returns:
            ExecutionTelemetry or None if not found.
        """
        stmt = select(ExecutionTelemetry).where(
            ExecutionTelemetry.execution_id == execution_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_agent(
        self,
        agent_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ExecutionTelemetry]:
        """
        Get telemetry records for a specific agent.

        Results are ordered by started_at descending (most recent first).

        Args:
            agent_id: UUID of the agent.
            limit: Maximum number of records to return.
            offset: Number of records to skip for pagination.

        Returns:
            List of ExecutionTelemetry records.
        """
        stmt = (
            select(ExecutionTelemetry)
            .where(ExecutionTelemetry.agent_id == agent_id)
            .order_by(ExecutionTelemetry.started_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_input_hash(
        self, input_hash: str
    ) -> Optional[ExecutionTelemetry]:
        """
        Find most recent successful execution with matching input hash.

        This supports deduplication (DB-08): if we already successfully
        processed this exact input, we can potentially skip re-execution.

        Args:
            input_hash: SHA-256 hash of the input data.

        Returns:
            Most recent successful ExecutionTelemetry with matching input,
            or None if no successful match exists.
        """
        stmt = (
            select(ExecutionTelemetry)
            .where(
                ExecutionTelemetry.input_hash == input_hash,
                ExecutionTelemetry.outcome == "success",
            )
            .order_by(ExecutionTelemetry.started_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_aggregation(
        self,
        agent_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> TelemetryAggregation:
        """
        Get aggregated telemetry statistics for an agent.

        Computes execution counts, success rates, latency statistics,
        and token usage over the specified time period.

        Args:
            agent_id: UUID of the agent.
            start_time: Start of aggregation period (inclusive).
            end_time: End of aggregation period (inclusive).

        Returns:
            TelemetryAggregation with computed statistics.
        """
        # Build base query with time filters
        base_filter = [ExecutionTelemetry.agent_id == agent_id]
        if start_time:
            base_filter.append(ExecutionTelemetry.started_at >= start_time)
        if end_time:
            base_filter.append(ExecutionTelemetry.started_at <= end_time)

        # Count by outcome
        stmt = (
            select(
                func.count().label("total"),
                func.sum(
                    func.cast(ExecutionTelemetry.outcome == "success", sqlalchemy_int())
                ).label("successful"),
                func.sum(
                    func.cast(ExecutionTelemetry.outcome == "error", sqlalchemy_int())
                ).label("failed"),
                func.sum(
                    func.cast(ExecutionTelemetry.outcome == "timeout", sqlalchemy_int())
                ).label("timeout"),
                func.sum(
                    func.cast(ExecutionTelemetry.outcome == "cancelled", sqlalchemy_int())
                ).label("cancelled"),
                func.avg(ExecutionTelemetry.latency_ms).label("avg_latency"),
                func.min(ExecutionTelemetry.latency_ms).label("min_latency"),
                func.max(ExecutionTelemetry.latency_ms).label("max_latency"),
                func.sum(ExecutionTelemetry.tokens_input).label("total_input"),
                func.sum(ExecutionTelemetry.tokens_output).label("total_output"),
                func.sum(ExecutionTelemetry.tokens_total).label("total_tokens"),
            )
            .where(*base_filter)
        )

        result = await self.session.execute(stmt)
        row = result.one()

        total = row.total or 0
        successful = row.successful or 0
        failed = row.failed or 0
        timeout = row.timeout or 0
        cancelled = row.cancelled or 0

        # Calculate success rate
        success_rate = (successful / total * 100) if total > 0 else 0.0

        # Calculate average tokens per execution
        total_tokens = row.total_tokens or 0
        avg_tokens = (total_tokens / total) if total > 0 else None

        return TelemetryAggregation(
            agent_id=agent_id,
            total_executions=total,
            successful_executions=successful,
            failed_executions=failed,
            timeout_executions=timeout,
            cancelled_executions=cancelled,
            success_rate=success_rate,
            avg_latency_ms=row.avg_latency,
            min_latency_ms=row.min_latency,
            max_latency_ms=row.max_latency,
            # p50, p95, p99 require window functions - simplified here
            p50_latency_ms=None,
            p95_latency_ms=None,
            p99_latency_ms=None,
            total_tokens_input=row.total_input or 0,
            total_tokens_output=row.total_output or 0,
            total_tokens=total_tokens,
            avg_tokens_per_execution=avg_tokens,
            period_start=start_time,
            period_end=end_time,
        )


def sqlalchemy_int():
    """Helper to get SQLAlchemy Integer type for casting."""
    from sqlalchemy import Integer
    return Integer
