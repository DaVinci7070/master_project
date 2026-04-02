"""
Agent Cleanup Watchdog for removing orphaned spawned agents.

This service runs periodically to:
1. Detect agents that have been running too long (stale)
2. Detect agents whose processes have died without cleanup
3. Remove orphaned agents from the registry
4. Log cleanup events for debugging

Prevents RESEARCH.md pitfall #3: Zombie containers/agents accumulating.

Configuration:
- cleanup_interval_seconds: How often to run (default 300s = 5 min)
- max_agent_age_seconds: When agent is considered stale (default 3600s = 1 hour)

Usage:
    registry = RuntimeAgentRegistry()
    watchdog = AgentCleanupWatchdog(registry)

    # Start background task
    asyncio.create_task(watchdog.start())

    # Stop when shutting down
    await watchdog.stop()
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional

from opentelemetry import trace

from app.models.schemas.developer_team_schemas import AgentStatus
from app.services.runtime_agent_registry import RuntimeAgentRegistry
from app.core.observability import get_agent_tracer, get_agent_metrics

log = logging.getLogger(__name__)
tracer = get_agent_tracer()


class AgentCleanupWatchdog:
    """
    Background service for cleaning up orphaned agents.

    Runs on a configurable interval to detect and remove:
    - Stale agents (running longer than max_age)
    - Zombie agents (process died but still registered)

    Example:
        registry = RuntimeAgentRegistry(max_concurrent_agents=5)
        watchdog = AgentCleanupWatchdog(
            registry=registry,
            cleanup_interval_seconds=300,  # 5 minutes
            max_agent_age_seconds=3600,    # 1 hour
        )

        # Start in background
        task = asyncio.create_task(watchdog.start())

        # Later, graceful shutdown
        await watchdog.stop()
    """

    def __init__(
        self,
        registry: RuntimeAgentRegistry,
        cleanup_interval_seconds: int = 300,
        max_agent_age_seconds: int = 3600,
    ):
        """
        Initialize the watchdog.

        Args:
            registry: RuntimeAgentRegistry to monitor.
            cleanup_interval_seconds: Seconds between cleanup runs (default 5 min).
            max_agent_age_seconds: Age threshold for stale agents (default 1 hour).
        """
        self.registry = registry
        self.interval = cleanup_interval_seconds
        self.max_age = max_agent_age_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self.log = log

    async def start(self) -> None:
        """
        Start the watchdog background loop.

        Runs cleanup on interval until stop() is called.
        """
        if self._running:
            self.log.warning("Watchdog already running")
            return

        self._running = True
        self.log.info(
            f"Starting cleanup watchdog: interval={self.interval}s, "
            f"max_age={self.max_age}s"
        )

        while self._running:
            try:
                await self._run_cleanup()
            except Exception as e:
                self.log.error(f"Cleanup error: {e}", exc_info=True)

            # Wait for next interval
            try:
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break

        self.log.info("Cleanup watchdog stopped")

    async def stop(self) -> None:
        """
        Stop the watchdog gracefully.

        Completes current cleanup cycle before stopping.
        """
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_cleanup(self) -> None:
        """
        Run a single cleanup cycle.

        1. Get all registered agents
        2. Check for stale agents (age > max_age)
        3. Check for zombie agents (process dead but registered)
        4. Remove orphaned agents
        5. Log and record metrics
        """
        with tracer.start_as_current_span(
            "watchdog.cleanup_cycle",
            attributes={
                "watchdog.max_age_seconds": self.max_age,
            }
        ) as span:
            # Get all agents
            all_agents = await self.registry.list_all()
            span.set_attribute("watchdog.agents_total", len(all_agents))

            if not all_agents:
                return

            now = datetime.now(timezone.utc)
            cleaned_stale: List[str] = []
            cleaned_zombie: List[str] = []

            for agent in all_agents:
                should_cleanup = False
                reason = ""

                # Check if stale (too old)
                age_seconds = (now - agent.spawned_at).total_seconds()
                if age_seconds > self.max_age:
                    should_cleanup = True
                    reason = f"stale (age={age_seconds:.0f}s > max={self.max_age}s)"
                    cleaned_stale.append(agent.agent_id)

                # Check if zombie (running/pending but completed_at set, or very old running)
                elif agent.status in (AgentStatus.PENDING, AgentStatus.RUNNING):
                    if agent.completed_at is not None:
                        should_cleanup = True
                        reason = "zombie (has completed_at but still running)"
                        cleaned_zombie.append(agent.agent_id)

                    # Also check for agents stuck in PENDING for too long (30 min)
                    elif agent.status == AgentStatus.PENDING and age_seconds > 1800:
                        should_cleanup = True
                        reason = f"stuck pending (age={age_seconds:.0f}s)"
                        cleaned_stale.append(agent.agent_id)

                if should_cleanup:
                    self.log.warning(
                        f"Cleaning up orphaned agent: id={agent.agent_id[:8]}..., "
                        f"file={agent.file_path}, reason={reason}"
                    )

                    # Update status to CANCELLED before removing
                    await self.registry.update_status(
                        agent.agent_id,
                        AgentStatus.CANCELLED,
                        error_message=f"Cleaned up by watchdog: {reason}"
                    )

                    # Release slot if agent was holding one
                    if agent.status in (AgentStatus.PENDING, AgentStatus.RUNNING):
                        try:
                            await self.registry.release_slot()
                        except Exception:
                            pass

                    # Unregister
                    await self.registry.unregister(agent.agent_id)

            # Log summary
            total_cleaned = len(cleaned_stale) + len(cleaned_zombie)
            if total_cleaned > 0:
                self.log.info(
                    f"Cleanup complete: stale={len(cleaned_stale)}, "
                    f"zombie={len(cleaned_zombie)}"
                )
                span.set_attribute("watchdog.cleaned_total", total_cleaned)
                span.set_attribute("watchdog.cleaned_stale", len(cleaned_stale))
                span.set_attribute("watchdog.cleaned_zombie", len(cleaned_zombie))

    async def run_once(self) -> int:
        """
        Run cleanup once (for testing or manual trigger).

        Returns:
            Number of agents cleaned up.
        """
        all_before = await self.registry.list_all()
        await self._run_cleanup()
        all_after = await self.registry.list_all()
        return len(all_before) - len(all_after)

    def get_status(self) -> dict:
        """
        Get watchdog status.

        Returns:
            Dict with running status and config.
        """
        return {
            "running": self._running,
            "interval_seconds": self.interval,
            "max_age_seconds": self.max_age,
        }
