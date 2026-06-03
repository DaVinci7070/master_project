import logging
from graphlib import TopologicalSorter, CycleError
from typing import Optional

from app.orchestration.topology.models import Topology, ValidationResult, AgentNode

logger = logging.getLogger(__name__)


class TopologyValidator:
    """
    Validates agent topologies for cycles and dependency satisfaction.

    Uses Python's built-in graphlib.TopologicalSorter (per RESEARCH.md).
    Rejects invalid topologies, keeps previous valid one (per CONTEXT).
    """

    def __init__(self):
        """Initialize validator."""
        self._last_valid_topology: Optional[Topology] = None

    def validate(self, topology: Topology) -> ValidationResult:
        """
        Validate topology for cycles and missing dependencies.

        Per CONTEXT: If validation fails, reject change, keep previous valid.

        Args:
            topology: Topology to validate

        Returns:
            ValidationResult with execution order if valid
        """
        errors = []
        warnings = []

        active_agents = topology.get_active_agents()
        if not active_agents:
            return ValidationResult(
                is_valid=False,
                errors=["Topology has no active agents"]
            )

        dependency_graph = topology.get_dependency_graph()

        agent_ids = set(dependency_graph.keys())
        missing = []
        for agent_id, deps in dependency_graph.items():
            for dep in deps:
                if dep not in agent_ids:
                    missing.append((agent_id, dep))
                    errors.append(f"Agent {agent_id} depends on {dep} which is not active")

        if missing:
            return ValidationResult(
                is_valid=False,
                missing_dependencies=missing,
                errors=errors
            )

        try:
            ts = TopologicalSorter(dependency_graph)
            execution_order = list(ts.static_order())

            waves = self._compute_waves(dependency_graph, execution_order)

            artifact_warnings = self._validate_artifact_flow(topology)
            warnings.extend(artifact_warnings)

            self._last_valid_topology = topology

            logger.info(
                f"Topology validated: {len(execution_order)} agents in {len(waves)} waves"
            )

            return ValidationResult(
                is_valid=True,
                execution_order=execution_order,
                execution_waves=waves,
                warnings=warnings
            )

        except CycleError as e:
            cycle = list(e.args[1]) if len(e.args) > 1 else []
            logger.error(f"Topology contains cycle: {cycle}")

            return ValidationResult(
                is_valid=False,
                cycle_nodes=cycle,
                errors=[f"Topology contains cycle involving: {cycle}"]
            )

    def _compute_waves(
        self,
        dependency_graph: dict[str, list[str]],
        execution_order: list[str]
    ) -> list[list[str]]:
        """
        Compute parallel execution waves from dependency graph.

        Agents with no unsatisfied dependencies can run in parallel.
        """
        agent_wave: dict[str, int] = {}

        for agent_id in execution_order:
            deps = dependency_graph.get(agent_id, [])
            if not deps:
                agent_wave[agent_id] = 0
            else:
                max_dep_wave = max(agent_wave.get(dep, 0) for dep in deps)
                agent_wave[agent_id] = max_dep_wave + 1

        max_wave = max(agent_wave.values()) if agent_wave else 0
        waves = [[] for _ in range(max_wave + 1)]
        for agent_id, wave in agent_wave.items():
            waves[wave].append(agent_id)

        return waves

    def _validate_artifact_flow(self, topology: Topology) -> list[str]:
        """
        Validate artifact consumption/production compatibility.

        Returns warnings for mismatched artifact flows.
        """
        warnings = []

        producers: dict[str, list[str]] = {}
        consumers: dict[str, list[str]] = {}

        for agent in topology.get_active_agents():
            for art_type in agent.produces_artifacts:
                producers.setdefault(art_type, []).append(agent.agent_id)
            for art_type in agent.consumes_artifacts:
                consumers.setdefault(art_type, []).append(agent.agent_id)

        for art_type, consumer_ids in consumers.items():
            if art_type not in producers:
                warnings.append(
                    f"Artifact '{art_type}' consumed by {consumer_ids} but not produced by any agent"
                )

        for art_type, producer_ids in producers.items():
            if art_type not in consumers:
                logger.debug(f"Artifact '{art_type}' produced by {producer_ids} but not consumed")

        return warnings

    def get_last_valid_topology(self) -> Optional[Topology]:
        """
        Get last successfully validated topology.

        Per CONTEXT: Reject invalid, keep old valid.
        """
        return self._last_valid_topology

    def validate_or_fallback(self, topology: Topology) -> tuple[ValidationResult, Topology]:
        """
        Validate topology, fallback to last valid if invalid.

        Returns:
            (validation_result, topology_to_use)
        """
        result = self.validate(topology)

        if result.is_valid:
            return result, topology
        elif self._last_valid_topology:
            logger.warning(
                f"New topology invalid ({result.errors}), using previous valid topology"
            )
            return result, self._last_valid_topology
        else:
            return result, topology


def get_execution_order(topology: Topology) -> list[str]:
    """
    Convenience function to get execution order from topology.

    Raises ValueError if topology is invalid.
    """
    validator = TopologyValidator()
    result = validator.validate(topology)

    if not result.is_valid:
        raise ValueError(f"Invalid topology: {result.errors}")

    return result.execution_order


def get_execution_waves(topology: Topology) -> list[list[str]]:
    """
    Convenience function to get parallel execution waves.

    Raises ValueError if topology is invalid.
    """
    validator = TopologyValidator()
    result = validator.validate(topology)

    if not result.is_valid:
        raise ValueError(f"Invalid topology: {result.errors}")

    return result.execution_waves
