"""
Runtime Agent Registry for tracking dynamically spawned coding agents.

This registry exists separately from static YAML agent configs (agents_registry.yaml).
It tracks ephemeral agents that are spawned at runtime for complex tasks and
cleaned up after completion.

Key features:
- Async-safe with asyncio.Lock
- Semaphore-based concurrency limiting (max_concurrent_agents)
- Agent lifecycle tracking (pending -> running -> completed/failed)
- OpenTelemetry trace correlation
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from opentelemetry import trace

from app.models.schemas.developer_team_schemas import (
    AgentStatus,
    SpawnedAgent,
)

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class RuntimeAgentRegistry:
    """
    In-memory registry for dynamically spawned agents.

    Note: Static agents use YAML (agents_registry.yaml).
          Dynamic agents use this runtime registry.

    Thread-safety: All mutations protected by asyncio.Lock.
    Concurrency: Semaphore limits simultaneous active agents.

    Example:
        registry = RuntimeAgentRegistry(max_concurrent_agents=5)

        # Register a new agent
        agent = await registry.register(
            agent_id="uuid",
            task_id="task-uuid",
            file_path="src/models/user.py"
        )

        # Update status
        await registry.update_status(agent_id, AgentStatus.RUNNING, process_id=12345)

        # Complete and unregister
        await registry.unregister(agent_id)
    """

    def __init__(self, max_concurrent_agents: int = 5):
        """
        Initialize the runtime registry.

        Args:
            max_concurrent_agents: Maximum agents that can run simultaneously.
                                   Prevents runaway spawning (STATE.md concern).
        """
        self._agents: Dict[str, SpawnedAgent] = {}
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_concurrent_agents)
        self._max_concurrent = max_concurrent_agents

        log.info(f"RuntimeAgentRegistry initialized with max_concurrent={max_concurrent_agents}")

    async def acquire_slot(self) -> bool:
        """
        Acquire a slot for spawning a new agent.

        Uses semaphore to enforce max_concurrent_agents limit.
        Non-blocking: returns False if no slots available.

        Returns:
            True if slot acquired, False if at capacity.
        """
        # Try to acquire without blocking
        acquired = self._semaphore.locked() is False
        if acquired:
            await self._semaphore.acquire()
            log.debug(f"Acquired spawn slot, remaining={self._semaphore._value}")
        else:
            log.warning(f"No spawn slots available (max={self._max_concurrent})")
        return acquired

    async def release_slot(self) -> None:
        """Release a spawn slot after agent completes."""
        self._semaphore.release()
        log.debug(f"Released spawn slot, available={self._semaphore._value}")

    async def register(
        self,
        agent_id: str,
        task_id: str,
        file_path: str,
    ) -> SpawnedAgent:
        """
        Register a newly spawned agent.

        Args:
            agent_id: Unique UUID for the agent.
            task_id: Parent task UUID.
            file_path: File the agent is working on.

        Returns:
            Created SpawnedAgent instance.

        Raises:
            ValueError: If agent_id already registered.
        """
        # Get OpenTelemetry trace context
        trace_id = None
        span_id = None
        current_span = trace.get_current_span()
        if current_span and current_span.is_recording():
            span_context = current_span.get_span_context()
            if span_context.is_valid:
                trace_id = format(span_context.trace_id, '032x')
                span_id = format(span_context.span_id, '016x')

        agent = SpawnedAgent(
            agent_id=agent_id,
            task_id=task_id,
            file_path=file_path,
            status=AgentStatus.PENDING,
            spawned_at=datetime.now(timezone.utc),
            trace_id=trace_id,
            span_id=span_id,
        )

        async with self._lock:
            if agent_id in self._agents:
                raise ValueError(f"Agent already registered: {agent_id}")

            self._agents[agent_id] = agent
            log.info(
                f"Registered agent id={agent_id[:8]}..., "
                f"task={task_id[:8]}..., file={file_path}"
            )

        return agent

    async def update_status(
        self,
        agent_id: str,
        status: AgentStatus,
        process_id: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> Optional[SpawnedAgent]:
        """
        Update agent status.

        Args:
            agent_id: Agent to update.
            status: New status.
            process_id: OS process ID (set when RUNNING).
            error_message: Error details (set when FAILED).

        Returns:
            Updated agent or None if not found.
        """
        async with self._lock:
            agent = self._agents.get(agent_id)
            if not agent:
                log.warning(f"Cannot update status: agent not found id={agent_id}")
                return None

            # Create updated agent (Pydantic models are immutable-ish)
            update_data = {"status": status}
            if process_id is not None:
                update_data["process_id"] = process_id
            if status in (AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.CANCELLED):
                update_data["completed_at"] = datetime.now(timezone.utc)

            updated = agent.model_copy(update=update_data)
            self._agents[agent_id] = updated

            log.info(f"Updated agent id={agent_id[:8]}... status={status.value}")
            return updated

    async def get(self, agent_id: str) -> Optional[SpawnedAgent]:
        """
        Get agent by ID.

        Args:
            agent_id: Agent UUID.

        Returns:
            SpawnedAgent or None if not found.
        """
        async with self._lock:
            return self._agents.get(agent_id)

    async def get_by_task(self, task_id: str) -> List[SpawnedAgent]:
        """
        Get all agents for a task.

        Args:
            task_id: Parent task UUID.

        Returns:
            List of agents belonging to this task.
        """
        async with self._lock:
            return [
                agent for agent in self._agents.values()
                if agent.task_id == task_id
            ]

    async def get_active(self) -> List[SpawnedAgent]:
        """
        Get all currently active agents (PENDING or RUNNING).

        Returns:
            List of active agents.
        """
        async with self._lock:
            return [
                agent for agent in self._agents.values()
                if agent.status in (AgentStatus.PENDING, AgentStatus.RUNNING)
            ]

    async def unregister(self, agent_id: str) -> Optional[SpawnedAgent]:
        """
        Remove agent from registry (cleanup).

        Called after agent completes or is cancelled.

        Args:
            agent_id: Agent to remove.

        Returns:
            Removed agent or None if not found.
        """
        async with self._lock:
            agent = self._agents.pop(agent_id, None)
            if agent:
                log.info(f"Unregistered agent id={agent_id[:8]}...")
            return agent

    async def list_all(self) -> List[SpawnedAgent]:
        """
        List all registered agents.

        Returns:
            List of all agents in registry.
        """
        async with self._lock:
            return list(self._agents.values())

    async def count_by_status(self) -> Dict[AgentStatus, int]:
        """
        Count agents by status.

        Returns:
            Dict mapping status to count.
        """
        async with self._lock:
            counts: Dict[AgentStatus, int] = {}
            for agent in self._agents.values():
                counts[agent.status] = counts.get(agent.status, 0) + 1
            return counts

    async def cleanup_stale(self, max_age_seconds: int = 3600) -> List[str]:
        """
        Remove agents older than max_age that are still registered.

        Called by cleanup watchdog to prevent memory leaks.

        Args:
            max_age_seconds: Max age before considered stale (default 1 hour).

        Returns:
            List of removed agent IDs.
        """
        now = datetime.now(timezone.utc)
        removed = []

        async with self._lock:
            stale_ids = []
            for agent_id, agent in self._agents.items():
                age = (now - agent.spawned_at).total_seconds()
                if age > max_age_seconds:
                    stale_ids.append(agent_id)

            for agent_id in stale_ids:
                agent = self._agents.pop(agent_id)
                removed.append(agent_id)
                age = (now - agent.spawned_at).total_seconds()
                log.warning(
                    f"Cleaned up stale agent id={agent_id[:8]}..., "
                    f"status={agent.status.value}, age={age:.0f}s"
                )

        if removed:
            log.info(f"Cleaned up {len(removed)} stale agents")

        return removed
