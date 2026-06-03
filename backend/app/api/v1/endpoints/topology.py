import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.dependencies.dependencies import get_db_session
from app.repositories.topology_repository import TopologyRepository
from app.models.sql.versioned_models import Agent
from app.models.sql.topology_models import TopologyChangeLog
from app.orchestration.topology.service import TopologyService

router = APIRouter(prefix="/topology", tags=["topology"])
log = logging.getLogger(__name__)


class ReactFlowPosition(BaseModel):
    """Position for React Flow node."""
    x: float = 0.0
    y: float = 0.0


class ReactFlowNodeData(BaseModel):
    """Data payload for React Flow node."""
    label: str
    agent_id: str
    capabilities: list[str] = Field(default_factory=list)
    is_active: bool = True
    prompt_id: Optional[str] = None
    io_schema: dict = Field(default_factory=dict)


class ReactFlowNode(BaseModel):
    """React Flow node format."""
    id: str
    type: str = "default"
    position: ReactFlowPosition
    data: ReactFlowNodeData


class ReactFlowEdge(BaseModel):
    """React Flow edge format."""
    id: str
    source: str
    target: str
    type: str = "default"
    animated: bool = False
    label: Optional[str] = None


class TopologyResponse(BaseModel):
    """Complete topology in React Flow format."""
    nodes: list[ReactFlowNode]
    edges: list[ReactFlowEdge]
    topology_id: str
    name: str
    agent_count: int
    edge_count: int
    created_at: str


class AgentNodeResponse(BaseModel):
    """Agent node for frontend topology view."""
    agent_id: str
    name: str
    prompt_id: Optional[str] = None
    capabilities: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    config: dict = Field(default_factory=dict)
    is_active: bool = True
    input_schema: Optional[dict] = None
    output_schema: Optional[dict] = None
    consumes_artifacts: list[str] = Field(default_factory=list)
    produces_artifacts: list[str] = Field(default_factory=list)
    source: str = "initial"
    agent_metadata: Optional[dict] = None
    created_at: Optional[str] = None


class FrontendTopologyResponse(BaseModel):
    """Topology format expected by frontend."""
    topology_id: str
    name: str
    description: Optional[str] = None
    agents: list[AgentNodeResponse]
    created_at: str
    is_active: bool = True
    version: int = 1


class TopologyHistoryEntry(BaseModel):
    """Historical topology change entry.

    The ``previous_state`` / ``new_state`` fields carry the JSON snapshots
    stored on TopologyChangeLog so the Evolution-UI can render a
    side-by-side diff (Sprint 2 / F6).
    """
    id: str
    timestamp: str
    change_type: str
    description: str
    affected_agents: list[str] = Field(default_factory=list)
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    entity_name: Optional[str] = None
    source: Optional[str] = None
    triggered_by: Optional[str] = None
    change_details: Optional[dict] = None
    previous_state: Optional[dict] = None
    new_state: Optional[dict] = None


class TopologyHistoryResponse(BaseModel):
    """Topology change history."""
    entries: list[TopologyHistoryEntry]
    total: int


def _compute_auto_layout(agents: list, edges: list) -> dict[str, ReactFlowPosition]:
    """
    Compute auto-layout positions for agents.

    Uses topological ordering to arrange nodes in waves (layers).
    """
    deps = {a.id: a.dependencies or [] for a in agents}
    agent_ids = {a.id for a in agents}

    waves = []
    remaining = set(agent_ids)

    while remaining:
        wave = []
        for agent_id in remaining:
            agent_deps = set(deps.get(agent_id, []))
            unsatisfied = agent_deps & remaining
            if not unsatisfied:
                wave.append(agent_id)

        if not wave:
            wave = list(remaining)

        waves.append(wave)
        remaining -= set(wave)

    positions = {}
    x_spacing = 250
    y_spacing = 150

    for wave_idx, wave in enumerate(waves):
        y = wave_idx * y_spacing
        for node_idx, agent_id in enumerate(wave):
            x = node_idx * x_spacing
            x -= (len(wave) - 1) * x_spacing / 2
            positions[agent_id] = ReactFlowPosition(x=x, y=y)

    return positions


@router.get("", response_model=FrontendTopologyResponse)
async def get_topology(
    include_inactive: bool = Query(False, description="Include inactive agents"),
    session: AsyncSession = Depends(get_db_session),
) -> FrontendTopologyResponse:
    """
    Get current topology with agents for frontend visualization.

    Returns agents with their dependencies for the topology graph component.
    """
    log.info(f"Getting topology: include_inactive={include_inactive}")

    repo = TopologyRepository(session)

    if include_inactive:
        result = await session.execute(select(Agent))
        agents = list(result.scalars().all())
    else:
        agents = await repo.get_all_active_agents()

    if not agents:
        return FrontendTopologyResponse(
            topology_id="empty",
            name="Empty Topology",
            description=None,
            agents=[],
            created_at=datetime.utcnow().isoformat(),
            is_active=True,
            version=1,
        )

    name_to_id = {agent.name: agent.id for agent in agents}

    agent_nodes = []
    for agent in agents:
        io_schema = agent.io_schema or {}
        resolved_deps = []
        for dep in (agent.dependencies or []):
            if dep in name_to_id:
                resolved_deps.append(name_to_id[dep])
            else:
                resolved_deps.append(dep)

        agent_nodes.append(AgentNodeResponse(
            agent_id=agent.id,
            name=agent.name,
            prompt_id=agent.prompt_id,
            capabilities=[],
            dependencies=resolved_deps,
            skill_ids=[],
            config={},
            is_active=agent.is_active,
            input_schema=io_schema.get("input"),
            output_schema=io_schema.get("output"),
            consumes_artifacts=io_schema.get("consumes", []),
            produces_artifacts=io_schema.get("produces", []),
            source=agent.source or "initial",
            agent_metadata=agent.agent_metadata,
            created_at=agent.created_at.isoformat() if agent.created_at else None,
        ))

    topology_id = f"db-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

    return FrontendTopologyResponse(
        topology_id=topology_id,
        name="Current Topology",
        description="Live topology from database",
        agents=agent_nodes,
        created_at=datetime.utcnow().isoformat(),
        is_active=True,
        version=1,
    )


@router.get("/reactflow", response_model=TopologyResponse)
async def get_topology_reactflow(
    include_inactive: bool = Query(False, description="Include inactive agents"),
    session: AsyncSession = Depends(get_db_session),
) -> TopologyResponse:
    """
    Get current topology as nodes/edges for React Flow (alternative format).

    Auto-layouts nodes based on dependency waves.
    """
    log.info(f"Getting topology (reactflow format): include_inactive={include_inactive}")

    repo = TopologyRepository(session)

    if include_inactive:
        result = await session.execute(select(Agent))
        agents = list(result.scalars().all())
    else:
        agents = await repo.get_all_active_agents()

    if not agents:
        return TopologyResponse(
            nodes=[],
            edges=[],
            topology_id="empty",
            name="Empty Topology",
            agent_count=0,
            edge_count=0,
            created_at=datetime.utcnow().isoformat(),
        )

    agent_ids = {a.id for a in agents}
    edges = []
    for agent in agents:
        for dep_id in (agent.dependencies or []):
            if dep_id in agent_ids:
                edges.append({
                    "source": dep_id,
                    "target": agent.id,
                })

    positions = _compute_auto_layout(agents, edges)

    nodes = []
    for agent in agents:
        pos = positions.get(agent.id, ReactFlowPosition(x=0, y=0))
        nodes.append(ReactFlowNode(
            id=agent.id,
            type="default",
            position=pos,
            data=ReactFlowNodeData(
                label=agent.name,
                agent_id=agent.id,
                capabilities=[],
                is_active=agent.is_active,
                prompt_id=agent.prompt_id,
                io_schema=agent.io_schema or {},
            ),
        ))

    rf_edges = []
    for i, edge in enumerate(edges):
        rf_edges.append(ReactFlowEdge(
            id=f"edge-{i}",
            source=edge["source"],
            target=edge["target"],
            type="default",
            animated=False,
        ))

    topology_id = f"db-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

    return TopologyResponse(
        nodes=nodes,
        edges=rf_edges,
        topology_id=topology_id,
        name="Current Topology",
        agent_count=len(nodes),
        edge_count=len(rf_edges),
        created_at=datetime.utcnow().isoformat(),
    )


@router.get("/history", response_model=TopologyHistoryResponse)
async def get_topology_history(
    limit: int = Query(20, ge=1, le=100, description="Max entries"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type: agent, skill, prompt"),
    source: Optional[str] = Query(None, description="Filter by source: system, manual, migration"),
    session: AsyncSession = Depends(get_db_session),
) -> TopologyHistoryResponse:
    """
    Get topology changes over time.

    Shows agent additions, removals, and dependency changes.
    """
    log.info(f"Getting topology history: limit={limit}, offset={offset}")

    topology_service = TopologyService(session)
    changes = await topology_service.get_recent_changes(
        limit=limit + offset,
        entity_type=entity_type,
        source=source
    )

    paginated = changes[offset:offset + limit]

    entries = []
    for change in paginated:
        description = f"{change.change_type.replace('_', ' ').title()}"
        if change.entity_name:
            description += f": {change.entity_name}"
        if change.change_details:
            if "reason" in change.change_details:
                description += f" ({change.change_details['reason']})"

        entries.append(TopologyHistoryEntry(
            id=change.id,
            timestamp=change.created_at.isoformat() if change.created_at else "",
            change_type=change.change_type,
            description=description,
            affected_agents=[change.entity_id] if change.entity_type == "agent" else [],
            entity_type=change.entity_type,
            entity_id=change.entity_id,
            entity_name=change.entity_name,
            source=change.source,
            triggered_by=change.triggered_by,
            change_details=change.change_details,
            previous_state=change.previous_state,
            new_state=change.new_state,
        ))

    return TopologyHistoryResponse(
        entries=entries,
        total=len(changes),
    )


@router.get("/stats")
async def get_topology_stats(
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Get topology statistics including agent counts by source.
    """
    topology_service = TopologyService(session)
    return await topology_service.get_topology_stats()
