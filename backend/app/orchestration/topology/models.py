"""Data structures for dynamic agent topology."""
from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class AgentNode(BaseModel):
    """
    Represents an agent in the topology graph.

    Contains configuration needed to execute the agent dynamically.
    """
    agent_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique identifier for this agent"
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Human-readable agent name"
    )
    prompt_id: Optional[str] = Field(
        default=None,
        description="Reference to prompt in database"
    )
    capabilities: list[str] = Field(
        default_factory=list,
        description="List of capabilities this agent provides"
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="Agent IDs this agent depends on (must run first)"
    )
    skill_ids: list[str] = Field(
        default_factory=list,
        description="Skills available to this agent"
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Agent-specific configuration"
    )
    is_active: bool = Field(
        default=True,
        description="Whether agent is active in topology"
    )

    # IO Schema for runtime validation
    input_schema: Optional[dict[str, Any]] = Field(
        default=None,
        description="JSON Schema for agent input"
    )
    output_schema: Optional[dict[str, Any]] = Field(
        default=None,
        description="JSON Schema for agent output"
    )

    # Artifact declarations for pre-validation
    consumes_artifacts: list[str] = Field(
        default_factory=list,
        description="Artifact types this agent consumes"
    )
    produces_artifacts: list[str] = Field(
        default_factory=list,
        description="Artifact types this agent produces"
    )

    @field_validator("agent_id")
    @classmethod
    def validate_agent_id(cls, v: str) -> str:
        """Ensure agent_id is valid identifier."""
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("agent_id must be alphanumeric with underscores/hyphens")
        return v

    model_config = {"frozen": True}


class AgentEdge(BaseModel):
    """
    Represents a dependency edge in the topology graph.

    from_agent must complete before to_agent can start.
    """
    from_agent_id: str = Field(..., description="Source agent (dependency)")
    to_agent_id: str = Field(..., description="Target agent (dependent)")
    edge_type: str = Field(
        default="dependency",
        description="Type of relationship (dependency, data_flow, etc.)"
    )

    model_config = {"frozen": True}


class Topology(BaseModel):
    """
    Complete agent topology representing the execution graph.

    Contains all agents and their dependency relationships.
    Used for validation and execution order computation.
    """
    topology_id: str = Field(
        ...,
        description="Unique identifier for this topology version"
    )
    name: str = Field(
        ...,
        description="Human-readable topology name"
    )
    description: Optional[str] = Field(
        default=None,
        description="Topology description"
    )
    agents: list[AgentNode] = Field(
        default_factory=list,
        description="All agents in the topology"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When topology was created"
    )
    is_active: bool = Field(
        default=True,
        description="Whether this is the active topology"
    )
    version: int = Field(
        default=1,
        description="Topology version number"
    )

    @model_validator(mode="after")
    def validate_dependencies_exist(self) -> "Topology":
        """Ensure all referenced dependencies exist in topology."""
        agent_ids = {agent.agent_id for agent in self.agents}
        for agent in self.agents:
            for dep_id in agent.dependencies:
                if dep_id not in agent_ids:
                    raise ValueError(
                        f"Agent {agent.agent_id} depends on {dep_id} which is not in topology"
                    )
        return self

    def get_agent(self, agent_id: str) -> Optional[AgentNode]:
        """Get agent by ID."""
        for agent in self.agents:
            if agent.agent_id == agent_id:
                return agent
        return None

    def get_active_agents(self) -> list[AgentNode]:
        """Get only active agents."""
        return [a for a in self.agents if a.is_active]

    def get_dependency_graph(self) -> dict[str, list[str]]:
        """
        Get dependency graph for validation.

        Returns dict mapping agent_id -> list of predecessor agent_ids.
        """
        return {
            agent.agent_id: agent.dependencies
            for agent in self.get_active_agents()
        }

    def get_edges(self) -> list[AgentEdge]:
        """Get all dependency edges."""
        edges = []
        for agent in self.agents:
            for dep_id in agent.dependencies:
                edges.append(AgentEdge(
                    from_agent_id=dep_id,
                    to_agent_id=agent.agent_id
                ))
        return edges


class ValidationResult(BaseModel):
    """Result of topology validation."""
    is_valid: bool
    execution_order: Optional[list[str]] = None
    execution_waves: Optional[list[list[str]]] = None
    cycle_nodes: Optional[list[str]] = None
    missing_dependencies: Optional[list[tuple[str, str]]] = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
