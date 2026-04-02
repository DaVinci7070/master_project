"""
Orchestration package for Lumari.

This package provides:
- GenericAgentExecutor: Database-driven agent execution
- HybridOrchestrator: Wave-based parallel coordination
- TopologyLoader: Database topology management
- SharedMemoryService: Hybrid memory with Qdrant + PostgreSQL
- AgentMigrator: Migration utility for hardcoded agents

See docs/ARCHITECTURE.md for the dual execution model:
- Dynamic agents via GenericAgentExecutor
- Specialized services via Parallel Stack (app/services/)
"""

from app.orchestration.executors.generic_executor import GenericAgentExecutor
from app.orchestration.orchestrators.hybrid_orchestrator import HybridOrchestrator
from app.orchestration.topology.loader import TopologyLoader
from app.orchestration.topology.validator import TopologyValidator
from app.orchestration.shared_memory.service import SharedMemoryService
from app.orchestration.shared_memory.qdrant_adapter import SharedMemoryQdrantAdapter
from app.orchestration.migration.agent_migrator import AgentMigrator
from app.orchestration.artifacts.pool import ArtifactPool
from app.orchestration.context_manager import ContextBudgetManager

# Intervention module (Phase 10)
from app.orchestration.intervention import (
    InterventionOrchestrator,
    create_intervention_orchestrator,
)

__all__ = [
    "GenericAgentExecutor",
    "HybridOrchestrator",
    "TopologyLoader",
    "TopologyValidator",
    "SharedMemoryService",
    "SharedMemoryQdrantAdapter",
    "AgentMigrator",
    "ArtifactPool",
    "ContextBudgetManager",
    # Intervention (Phase 10)
    "InterventionOrchestrator",
    "create_intervention_orchestrator",
]
