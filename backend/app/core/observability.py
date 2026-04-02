"""
Enhanced observability for Developer Team spawned agents.

Provides utilities for:
- Setting up agent-specific OpenTelemetry tracing
- Creating spans with agent context attributes
- Propagating trace context to spawned agents
- Structured event logging for agent lifecycle

This extends the existing telemetry infrastructure (Phase 1) with
patterns specific to dynamic agent spawning and multi-agent coordination.
"""
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, Optional

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

log = logging.getLogger(__name__)

# Agent-specific tracer (separate from module tracers for filtering)
AGENT_TRACER_NAME = "lumari.developer_team.agents"


def get_agent_tracer() -> trace.Tracer:
    """
    Get the tracer for spawned agent operations.

    Using a dedicated tracer name allows filtering agent traces
    separately from other application traces.

    Returns:
        Tracer instance for agent operations.
    """
    return trace.get_tracer(AGENT_TRACER_NAME)


@contextmanager
def create_agent_span(
    operation: str,
    agent_id: str,
    task_id: str,
    file_path: str,
    additional_attributes: Optional[Dict[str, Any]] = None,
) -> Generator[Span, None, None]:
    """
    Create an OpenTelemetry span for an agent operation.

    Standard attributes for all agent spans:
    - agent.id: Unique identifier
    - agent.task_id: Parent task
    - agent.file_path: File being worked on
    - agent.operation: spawn|execute|complete|cleanup|cancel

    Args:
        operation: Operation name (spawn, execute, complete, etc.)
        agent_id: Agent UUID.
        task_id: Parent task UUID.
        file_path: File the agent is working on.
        additional_attributes: Extra attributes to add.

    Yields:
        Span context for the operation.

    Example:
        with create_agent_span("spawn", agent_id, task_id, "model.py") as span:
            # Do spawn operation
            span.set_attribute("agent.process_id", pid)
    """
    tracer = get_agent_tracer()

    attributes = {
        "agent.id": agent_id,
        "agent.task_id": task_id,
        "agent.file_path": file_path,
        "agent.operation": operation,
        "agent.timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if additional_attributes:
        attributes.update(additional_attributes)

    with tracer.start_as_current_span(
        f"agent.{operation}",
        kind=SpanKind.INTERNAL,
        attributes=attributes,
    ) as span:
        try:
            yield span
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR))
            span.record_exception(e)
            raise


def record_agent_event(
    span: Span,
    event_name: str,
    attributes: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Record an event on an agent span.

    Events provide additional context at specific points in time:
    - agent.registered
    - agent.status_changed
    - agent.code_generated
    - agent.timeout
    - agent.error

    Args:
        span: Current span to add event to.
        event_name: Name of the event.
        attributes: Event attributes.
    """
    if span and span.is_recording():
        span.add_event(
            name=event_name,
            attributes=attributes or {},
        )


def get_trace_context() -> Dict[str, str]:
    """
    Get current trace context for propagation to spawned agents.

    Returns dict with trace_id and span_id that can be passed
    to spawned agents for context correlation.

    Returns:
        Dict with trace_id and span_id, or empty if no active span.
    """
    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
        span_context = current_span.get_span_context()
        if span_context.is_valid:
            return {
                "trace_id": format(span_context.trace_id, '032x'),
                "span_id": format(span_context.span_id, '016x'),
            }
    return {}


def set_agent_success(span: Span, tokens_used: int = 0, duration_seconds: float = 0) -> None:
    """
    Mark agent span as successful with metrics.

    Args:
        span: Span to update.
        tokens_used: LLM tokens consumed.
        duration_seconds: Execution duration.
    """
    if span and span.is_recording():
        span.set_status(Status(StatusCode.OK))
        span.set_attribute("agent.success", True)
        span.set_attribute("agent.tokens_used", tokens_used)
        span.set_attribute("agent.duration_seconds", duration_seconds)


def set_agent_failure(span: Span, error_message: str, error_type: str = "unknown") -> None:
    """
    Mark agent span as failed with error details.

    Args:
        span: Span to update.
        error_message: Error description.
        error_type: Error classification.
    """
    if span and span.is_recording():
        span.set_status(Status(StatusCode.ERROR))
        span.set_attribute("agent.success", False)
        span.set_attribute("agent.error_message", error_message)
        span.set_attribute("agent.error_type", error_type)


class AgentMetrics:
    """
    Simple in-memory metrics for agent operations.

    Tracks:
    - Spawn counts (total, success, failure)
    - Execution times
    - Token usage

    For production, these would integrate with Prometheus/StatsD.
    """

    def __init__(self):
        self.spawns_total = 0
        self.spawns_success = 0
        self.spawns_failed = 0
        self.total_tokens = 0
        self.total_duration_seconds = 0.0
        self._lock = None  # Will use asyncio.Lock in async context

    def record_spawn(self, success: bool, tokens: int = 0, duration: float = 0) -> None:
        """Record a spawn completion."""
        self.spawns_total += 1
        if success:
            self.spawns_success += 1
        else:
            self.spawns_failed += 1
        self.total_tokens += tokens
        self.total_duration_seconds += duration

    def get_stats(self) -> Dict[str, Any]:
        """Get current metrics."""
        return {
            "spawns_total": self.spawns_total,
            "spawns_success": self.spawns_success,
            "spawns_failed": self.spawns_failed,
            "success_rate": (
                self.spawns_success / self.spawns_total
                if self.spawns_total > 0 else 0
            ),
            "total_tokens": self.total_tokens,
            "total_duration_seconds": self.total_duration_seconds,
            "avg_duration_seconds": (
                self.total_duration_seconds / self.spawns_total
                if self.spawns_total > 0 else 0
            ),
        }


# Global metrics instance (singleton)
_agent_metrics: Optional[AgentMetrics] = None


def get_agent_metrics() -> AgentMetrics:
    """Get global agent metrics instance."""
    global _agent_metrics
    if _agent_metrics is None:
        _agent_metrics = AgentMetrics()
    return _agent_metrics
