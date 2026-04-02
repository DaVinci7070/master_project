"""
API endpoints for Server-Sent Events (SSE) streaming.

Provides real-time updates for execution monitoring and topology changes.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.dependencies.dependencies import get_db_session, AsyncSessionLocal
from app.models.sql.telemetry_models import ExecutionTelemetry
from app.models.sql.versioned_models import Agent
from app.models.sql.intervention_models import BlockedChallenge
from app.models.sql.agent_event_models import AgentExecutionEvent

router = APIRouter(prefix="/events", tags=["events"])
log = logging.getLogger(__name__)


# Event type constants
EVENT_EXECUTION_STARTED = "execution_started"
EVENT_EXECUTION_PROGRESS = "execution_progress"
EVENT_EXECUTION_COMPLETED = "execution_completed"
EVENT_EXECUTION_ERROR = "execution_error"
EVENT_TOPOLOGY_CHANGED = "topology_changed"
EVENT_AGENT_STATUS = "agent_status"
EVENT_HEARTBEAT = "heartbeat"


def format_sse_event(event_type: str, data: dict) -> str:
    """Format data as SSE event."""
    json_data = json.dumps(data)
    return f"event: {event_type}\ndata: {json_data}\n\n"


async def execution_event_generator(
    execution_id: str,
    poll_interval: float = 0.5,
    timeout: float = 300.0,
) -> AsyncGenerator[str, None]:
    """
    Generate SSE events for execution updates.

    Polls database for:
    - AgentExecutionEvent table for real-time agent_start/complete/error events
    - BlockedChallenge table for challenge status changes

    Creates a fresh database session for each poll iteration to avoid
    connection/transaction issues with long-running streams.
    """
    log.info(f"Starting execution stream: execution_id={execution_id}")

    start_time = asyncio.get_event_loop().time()
    last_challenge_status = None
    last_event_id = None  # Track last processed agent event
    heartbeat_counter = 0

    # Emit start event
    yield format_sse_event("start", {
        "type": "start",
        "execution_id": execution_id,
        "agent_id": "orchestrator",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    while True:
        # Check timeout
        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed > timeout:
            yield format_sse_event("timeout", {
                "message": f"Stream timed out after {timeout}s",
                "execution_id": execution_id,
            })
            break

        # Create fresh session for each poll iteration
        async with AsyncSessionLocal() as session:
            try:
                # Poll AgentExecutionEvent table for real-time agent events
                try:
                    agent_event_stmt = select(AgentExecutionEvent).where(
                        AgentExecutionEvent.execution_id == execution_id
                    ).order_by(AgentExecutionEvent.created_at.asc())

                    agent_event_result = await session.execute(agent_event_stmt)
                    agent_events = list(agent_event_result.scalars().all())

                    # Yield new agent events that we haven't sent yet
                    for agent_event in agent_events:
                        if last_event_id is None or agent_event.id > last_event_id:
                            event_data = {
                                "type": agent_event.event_type,
                                "execution_id": execution_id,
                                "agent_id": agent_event.agent_id,
                                "agent_name": agent_event.agent_name,
                                "wave": agent_event.wave,
                                "timestamp": agent_event.created_at.isoformat() if agent_event.created_at else datetime.now(timezone.utc).isoformat(),
                            }

                            if agent_event.data:
                                event_data["data"] = agent_event.data
                            if agent_event.error:
                                event_data["error"] = agent_event.error

                            yield format_sse_event(agent_event.event_type, event_data)
                            last_event_id = agent_event.id
                except Exception as agent_err:
                    # Table may not exist yet - continue silently
                    log.debug(f"Agent events query failed: {agent_err}")

                # Check BlockedChallenge status (primary source for challenge execution)
                challenge_stmt = select(BlockedChallenge).where(
                    BlockedChallenge.execution_id == execution_id
                )
                challenge_result = await session.execute(challenge_stmt)
                challenge = challenge_result.scalar_one_or_none()

                if challenge and challenge.status != last_challenge_status:
                    event_data = {
                        "type": "progress" if challenge.status == "executing" else challenge.status,
                        "execution_id": execution_id,
                        "agent_id": "orchestrator",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "challenge_status": challenge.status,
                    }

                    if challenge.status == "resolved":
                        event_data["type"] = "complete"
                        results = challenge.execution_results or {}
                        event_data["data"] = {
                            "success": results.get("success", True),
                            "duration_ms": results.get("duration_ms"),
                            "agents_executed": results.get("agents_executed", 0),
                        }
                        yield format_sse_event("complete", event_data)
                        return  # Exit generator
                    elif challenge.status == "failed":
                        event_data["type"] = "error"
                        results = challenge.execution_results or {}
                        event_data["error"] = results.get("error", "Execution failed")
                        yield format_sse_event("error", event_data)
                        return  # Exit generator
                    else:
                        yield format_sse_event("progress", event_data)

                    last_challenge_status = challenge.status

            except Exception as e:
                log.error(f"Error polling execution: {e}")

        # Periodic heartbeat to keep connection alive
        heartbeat_counter += 1
        if heartbeat_counter % 20 == 0:  # Every 10 seconds at 0.5s interval
            yield format_sse_event(EVENT_HEARTBEAT, {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": elapsed,
            })

        await asyncio.sleep(poll_interval)


async def topology_event_generator(
    poll_interval: float = 2.0,
    timeout: float = 3600.0,
) -> AsyncGenerator[str, None]:
    """
    Generate SSE events for topology changes.

    Polls for agent status changes and yields SSE events.
    Creates a fresh database session for each poll iteration.
    """
    log.info("Starting topology stream")

    start_time = asyncio.get_event_loop().time()
    last_agent_states: dict[str, bool] = {}
    heartbeat_counter = 0

    # Get initial state
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Agent))
            agents = list(result.scalars().all())
            last_agent_states = {a.id: a.is_active for a in agents}

            # Emit initial topology
            yield format_sse_event(EVENT_TOPOLOGY_CHANGED, {
                "type": "initial",
                "agent_count": len(agents),
                "active_count": sum(1 for a in agents if a.is_active),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as e:
        log.error(f"Error getting initial topology: {e}")

    while True:
        # Check timeout
        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed > timeout:
            yield format_sse_event("timeout", {
                "message": f"Stream timed out after {timeout}s",
            })
            break

        async with AsyncSessionLocal() as session:
            try:
                # Poll for changes
                result = await session.execute(select(Agent))
                agents = list(result.scalars().all())
                current_states = {a.id: a.is_active for a in agents}

                # Detect changes
                for agent_id, is_active in current_states.items():
                    if agent_id not in last_agent_states:
                        # New agent
                        agent = next((a for a in agents if a.id == agent_id), None)
                        yield format_sse_event(EVENT_TOPOLOGY_CHANGED, {
                            "type": "agent_added",
                            "agent_id": agent_id,
                            "agent_name": agent.name if agent else "unknown",
                            "is_active": is_active,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                    elif is_active != last_agent_states[agent_id]:
                        # Status changed
                        agent = next((a for a in agents if a.id == agent_id), None)
                        yield format_sse_event(EVENT_AGENT_STATUS, {
                            "agent_id": agent_id,
                            "agent_name": agent.name if agent else "unknown",
                            "is_active": is_active,
                            "previous_active": last_agent_states[agent_id],
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })

                # Detect removed agents
                for agent_id in last_agent_states:
                    if agent_id not in current_states:
                        yield format_sse_event(EVENT_TOPOLOGY_CHANGED, {
                            "type": "agent_removed",
                            "agent_id": agent_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })

                last_agent_states = current_states

            except Exception as e:
                log.error(f"Error polling topology: {e}")

        # Periodic heartbeat
        heartbeat_counter += 1
        if heartbeat_counter % 15 == 0:  # Every 30 seconds at 2s interval
            yield format_sse_event(EVENT_HEARTBEAT, {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": elapsed,
                "agent_count": len(last_agent_states),
            })

        await asyncio.sleep(poll_interval)


@router.get("/execution/{execution_id}")
async def stream_execution(
    execution_id: str,
) -> StreamingResponse:
    """
    SSE stream for execution updates.

    Streams events as execution progresses:
    - execution_progress: Status changes during execution
    - execution_completed: Execution finished successfully
    - execution_error: Execution failed
    - heartbeat: Keep-alive every 10 seconds

    Use with EventSource API in browser:
    ```javascript
    const source = new EventSource('/api/v1/events/execution/{id}');
    source.addEventListener('execution_completed', (e) => {
      const data = JSON.parse(e.data);
      console.log('Completed:', data);
    });
    ```
    """
    log.info(f"SSE stream requested: execution_id={execution_id}")

    return StreamingResponse(
        execution_event_generator(execution_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.get("/topology")
async def stream_topology() -> StreamingResponse:
    """
    SSE stream for topology changes.

    Streams events when topology changes:
    - topology_changed: Agent added/removed or topology reload
    - agent_status: Agent activated/deactivated
    - heartbeat: Keep-alive every 30 seconds

    Use with EventSource API in browser:
    ```javascript
    const source = new EventSource('/api/v1/events/topology');
    source.addEventListener('agent_status', (e) => {
      const data = JSON.parse(e.data);
      console.log('Agent status:', data);
    });
    ```
    """
    log.info("SSE topology stream requested")

    return StreamingResponse(
        topology_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
