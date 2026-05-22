"""
Telemetry service for managing execution telemetry.

This service provides a high-level interface for:
- Starting execution telemetry with input hashing
- Completing execution telemetry with output hashing and metrics
- Checking for duplicate inputs (deduplication via DB-08)
- Retrieving execution history and aggregations
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from opentelemetry import trace

from app.models.sql.telemetry_models import ExecutionTelemetry
from app.models.schemas.telemetry_schemas import (
    ExecutionTelemetryCreate,
    ExecutionTelemetryUpdate,
    ExecutionTelemetryResponse,
    TelemetryAggregation,
)
from app.repositories.telemetry_repository import TelemetryRepository, compute_hash

log = logging.getLogger(__name__)

# Get the tracer for this module
tracer = trace.get_tracer(__name__)


class TelemetryService:
    """
    Service for managing execution telemetry.

    This service handles the full lifecycle of execution telemetry:
    1. start_execution() - Called when agent execution begins
    2. complete_execution() - Called when agent execution ends
    3. check_duplicate() - Used to detect duplicate inputs
    4. get_execution_history() - Retrieve past executions
    5. get_aggregation() - Get statistical summaries
    """

    def __init__(self, repository: TelemetryRepository):
        """
        Initialize telemetry service with repository.

        Args:
            repository: TelemetryRepository for database operations.
        """
        self.repository = repository

    async def start_execution(
        self,
        agent_id: str,
        execution_id: str,
        input_data: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExecutionTelemetry:
        """
        Start tracking a new agent execution.

        This creates a new telemetry record with:
        - Computed input hash for deduplication (DB-08)
        - Current OpenTelemetry trace/span IDs
        - Initial outcome="running" state

        Args:
            agent_id: UUID of the executing agent.
            execution_id: UUID for this specific execution instance.
            input_data: Input data to hash for deduplication.
            metadata: Optional additional metadata for the execution.

        Returns:
            Created ExecutionTelemetry record.

        Example:
            telemetry = await service.start_execution(
                agent_id="abc-123",
                execution_id="exec-456",
                input_data={"query": "user question"},
                metadata={"source": "api"}
            )
        """
        log.info(f"Starting telemetry for agent={agent_id[:8]}..., execution={execution_id[:8]}...")

        # Compute input hash for deduplication
        input_hash = compute_hash(input_data)

        # Get current OpenTelemetry span context
        trace_id = None
        span_id = None
        current_span = trace.get_current_span()
        if current_span and current_span.is_recording():
            span_context = current_span.get_span_context()
            if span_context.is_valid:
                trace_id = format(span_context.trace_id, '032x')
                span_id = format(span_context.span_id, '016x')

        # Create telemetry record
        create_data = ExecutionTelemetryCreate(
            agent_id=agent_id,
            execution_id=execution_id,
            started_at=datetime.now(timezone.utc),
            input_hash=input_hash,
            outcome="running",  # Will be updated on completion
            trace_id=trace_id,
            span_id=span_id,
            execution_metadata=metadata or {},
        )

        telemetry = await self.repository.create(create_data)

        log.info(
            f"Started telemetry id={telemetry.id}, input_hash={input_hash[:16]}..., "
            f"trace_id={trace_id}"
        )

        return telemetry

    async def complete_execution(
        self,
        telemetry_id: str,
        output_data: Any,
        tokens_input: int = 0,
        tokens_output: int = 0,
        outcome: str = "success",
        error_message: Optional[str] = None,
        error_type: Optional[str] = None,
        metadata_updates: Optional[Dict[str, Any]] = None,
        on_complete: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> Optional[ExecutionTelemetry]:
        """
        Complete an execution and record final metrics.

        This updates the telemetry record with:
        - Computed output hash for deduplication
        - Latency calculation (completed_at - started_at)
        - Token usage counts
        - Final outcome status
        - Error details if applicable
        - OpenTelemetry span attributes

        Args:
            telemetry_id: UUID of the telemetry record to complete.
            output_data: Output data to hash for deduplication.
            tokens_input: Number of input tokens consumed.
            tokens_output: Number of output tokens generated.
            outcome: Final outcome (success, error, timeout, cancelled).
            error_message: Error message if outcome is error.
            error_type: Error type/class name if outcome is error.
            metadata_updates: Additional metadata to merge with existing.
            on_complete: Optional async callback called with execution_id after
                        successful completion. Use for triggering analysis
                        pipeline via BackgroundTasks.

        Returns:
            Updated ExecutionTelemetry or None if not found.

        Example:
            telemetry = await service.complete_execution(
                telemetry_id=telemetry.id,
                output_data={"response": "agent response"},
                tokens_input=150,
                tokens_output=200,
                outcome="success"
            )

            # With analysis trigger:
            async def trigger_analysis(execution_id: str):
                background_tasks.add_task(
                    run_analysis_pipeline,
                    execution_id,
                    input_content=str(input_data),
                    output_content=str(result),
                )

            await service.complete_execution(
                telemetry_id=telemetry.id,
                output_data=result,
                outcome="success",
                on_complete=trigger_analysis,
            )
        """
        log.info(f"Completing telemetry id={telemetry_id}, outcome={outcome}")

        # Get existing record to calculate latency
        existing = await self.repository.get_by_id(telemetry_id)
        if not existing:
            log.warning(f"Cannot complete telemetry: record not found id={telemetry_id}")
            return None

        # Calculate completion time and latency
        completed_at = datetime.now(timezone.utc)
        latency_ms = (completed_at - existing.started_at).total_seconds() * 1000

        # Compute output hash
        output_hash = compute_hash(output_data)

        # Merge metadata if provided
        merged_metadata = existing.execution_metadata.copy() if existing.execution_metadata else {}
        if metadata_updates:
            merged_metadata.update(metadata_updates)

        # Prepare update data
        update_data = ExecutionTelemetryUpdate(
            completed_at=completed_at,
            latency_ms=latency_ms,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            tokens_total=tokens_input + tokens_output,
            output_hash=output_hash,
            outcome=outcome,
            error_message=error_message,
            error_type=error_type,
            execution_metadata=merged_metadata,
        )

        # Update record
        telemetry = await self.repository.update(telemetry_id, update_data)

        # Set OpenTelemetry span attributes
        current_span = trace.get_current_span()
        if current_span and current_span.is_recording():
            current_span.set_attribute("telemetry.id", telemetry_id)
            current_span.set_attribute("telemetry.outcome", outcome)
            current_span.set_attribute("telemetry.latency_ms", latency_ms)
            current_span.set_attribute("telemetry.tokens_total", tokens_input + tokens_output)
            if error_type:
                current_span.set_attribute("telemetry.error_type", error_type)

        log.info(
            f"Completed telemetry id={telemetry_id}, latency={latency_ms:.2f}ms, "
            f"tokens={tokens_input + tokens_output}, output_hash={output_hash[:16]}..."
        )

        # Call completion callback if provided and execution was successful
        if on_complete and outcome == "success":
            try:
                await on_complete(existing.execution_id)
            except Exception as e:
                log.warning(f"Completion callback failed: {e}")

        return telemetry

    async def check_duplicate(
        self, input_data: Any
    ) -> Optional[ExecutionTelemetry]:
        """
        Check if this input was already successfully processed.

        This supports deduplication (DB-08): if we find a recent successful
        execution with the same input hash, callers can choose to skip
        re-execution and return the cached result.

        Args:
            input_data: Input data to check for duplicates.

        Returns:
            Most recent successful ExecutionTelemetry with matching input,
            or None if no duplicate exists.

        Example:
            existing = await service.check_duplicate(user_input)
            if existing:
                return existing.output_data  # Skip re-execution
        """
        input_hash = compute_hash(input_data)
        log.debug(f"Checking for duplicate input_hash={input_hash[:16]}...")

        duplicate = await self.repository.find_by_input_hash(input_hash)

        if duplicate:
            log.info(
                f"Found duplicate execution id={duplicate.id}, "
                f"completed_at={duplicate.completed_at}"
            )
        else:
            log.debug("No duplicate found")

        return duplicate

    async def get_execution_history(
        self,
        agent_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ExecutionTelemetryResponse]:
        """
        Get execution history for an agent.

        Returns recent executions ordered by start time (most recent first).

        Args:
            agent_id: UUID of the agent.
            limit: Maximum number of records to return.
            offset: Number of records to skip for pagination.

        Returns:
            List of ExecutionTelemetryResponse schemas.
        """
        log.debug(f"Getting execution history for agent={agent_id[:8]}..., limit={limit}")

        records = await self.repository.get_by_agent(
            agent_id=agent_id,
            limit=limit,
            offset=offset,
        )

        return [
            ExecutionTelemetryResponse.model_validate(record)
            for record in records
        ]

    async def get_aggregation(
        self,
        agent_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> TelemetryAggregation:
        """
        Get aggregated telemetry statistics for an agent.

        Computes statistics including:
        - Execution counts by outcome
        - Success rate percentage
        - Latency statistics (avg, min, max)
        - Token usage totals and averages

        Args:
            agent_id: UUID of the agent.
            start_time: Start of aggregation period (inclusive).
            end_time: End of aggregation period (inclusive).

        Returns:
            TelemetryAggregation with computed statistics.
        """
        log.debug(
            f"Getting aggregation for agent={agent_id[:8]}..., "
            f"start={start_time}, end={end_time}"
        )

        return await self.repository.get_aggregation(
            agent_id=agent_id,
            start_time=start_time,
            end_time=end_time,
        )

    async def get_by_execution_id(
        self, execution_id: str
    ) -> Optional[ExecutionTelemetryResponse]:
        """
        Get telemetry record by execution ID.

        Args:
            execution_id: UUID of the execution.

        Returns:
            ExecutionTelemetryResponse or None if not found.
        """
        record = await self.repository.get_by_execution_id(execution_id)
        if record:
            return ExecutionTelemetryResponse.model_validate(record)
        return None
