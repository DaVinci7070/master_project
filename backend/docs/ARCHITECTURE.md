# Lumari Backend Architecture

## Overview

Lumari uses a hybrid agent architecture with two execution paths:

1. **GenericAgentExecutor** - Database-driven agents with dynamic topology
2. **Parallel Stack** - Specialized Python services for complex integrations

This document explains the dual execution model and how the two paths coexist.

## Execution Paths

### 1. GenericAgentExecutor (Dynamic)

Location: `app/orchestration/executors/generic_executor.py`

Dynamic agents are:
- Defined in database (Agent, Prompt tables)
- Loaded via TopologyLoader
- Executed by GenericAgentExecutor
- Can be hot-swapped, A/B tested, and modified at runtime

**Characteristics:**
- All behavior defined by prompts + skills
- No hardcoded Python logic
- Template-based prompt injection ({context}, {artifacts}, {skills}, {input})
- Writes to both session artifacts AND shared memory (dual-write)

**When to use:** Standard agent workflows with clear input/output contracts where behavior is fully expressible via prompts.

### 2. Parallel Stack (Specialized)

Location: `app/services/*_service.py`

Specialized services remain as Python implementations when they:
- Have complex repository integrations (3-strike rule, history queries)
- Generate dynamic JSON schemas for LLM structured output
- Need tight coupling with domain-specific logic
- Require transaction management across multiple operations

**Current Parallel Stack Services:**

| Service | Purpose | Why Specialized |
|---------|---------|-----------------|
| ControlAgentService | Evaluate findings, enforce 3-strike rule | Complex repository integration, dynamic JSON schema, finding fingerprint tracking |
| ProductOwnerService | Prioritize findings | Pattern synthesis from historical context, finding correlation |
| AnalyzerService | Analyze telemetry | Deep integration with telemetry data structures, finding generation |
| QualityJudgeService | Score output quality | A/B test integration, dual comparison logic, statistical analysis |
| PromptEngineerService | Generate/modify prompts | Meta-prompting with schema validation, version tracking |
| ToolBuilderService | Generate/modify tools | Code validation, sandbox integration, security constraint enforcement |

**Key Distinction:** Parallel Stack services have Python logic beyond what prompts express. GenericAgentExecutor agents are prompt-only.

### Interoperability

Both execution paths can coexist and interoperate:

- GenericAgentExecutor agents write to SharedMemoryService
- Parallel Stack services can read from SharedMemory
- Both use the same Artifact format for output
- Both can be orchestrated by HybridOrchestrator
- Parallel Stack services can trigger GenericAgentExecutor workflows
- GenericAgentExecutor agents can produce inputs for Parallel Stack services

## Shared Memory Architecture

### Hybrid Storage

Shared memory uses a hybrid PostgreSQL + Qdrant approach:

- **PostgreSQL**: Metadata, relations, status tracking, project scoping
- **Qdrant**: Vector embeddings for RAG retrieval

### Core Entities

| Entity | Storage | Purpose |
|--------|---------|---------|
| Fact | PostgreSQL + Qdrant | Verified knowledge with confidence scores |
| Hypothesis | PostgreSQL + Qdrant | Unverified theories with supporting/contradicting links |
| Relation | PostgreSQL | Causal links between facts ("causes", "caused_by") |
| Artifact | Session-scoped | Agent outputs for current workflow |

### Cross-Project Retrieval

Facts, Hypotheses, and Relations include `project_id` to enable:
- Project-scoped retrieval (default)
- Cross-project pattern search (find similar issues in other projects)

### Retrieval Scoring

Combined retrieval uses weighted scoring:
- 70% semantic similarity (Qdrant vector search)
- 30% recency boost (prefer recent facts)
- Confidence-based contradiction detection (0.3 threshold)

## Topology Management

### Database Schema

The topology is stored in three primary tables:

- `agents` table: Agent definitions, capabilities, dependencies
- `prompts` table: System prompts with versioning via parent_id chain
- `artifact_schemas` table: IO schema definitions (JSON Schema stored as JSON)

### TopologyLoader

Location: `app/orchestration/topology/loader.py`

Features:
- `reload(force=True)` - Refresh topology from database
- `swap_agent_prompt()` - Swap prompts after A/B test validation
- Caches topology between runs for performance
- Eager skill loading at topology load time (not lazy)

### TopologyValidator

Location: `app/orchestration/topology/validator.py`

Validates:
- DAG structure (no cycles) using graphlib.TopologicalSorter
- Artifact schema compatibility between connected agents
- Wave assignment correctness

**Fallback Policy:** On validation failure, keeps last valid topology (graceful fallback per CONTEXT.md rejection policy).

### Hot Reload

Topology supports runtime updates:
- Database changes trigger reload on next request
- A/B test gate required for prompt swaps (is_significant=1)
- No downtime for topology changes

## Migration Path

To migrate a Parallel Stack service to GenericAgentExecutor:

1. **Extract prompt** to database via AgentMigrator
2. **Define IO schema** in artifact_schemas table
3. **Refactor service logic to skills** (if behavior can be expressed as tools)
4. **Create Agent record** pointing to prompt and skills
5. **Test via A/B comparison** - run both paths, compare outputs
6. **Deprecate Python service** after validation

**Note:** Not all services can be migrated. Complex integrations (like 3-strike rule) may require Parallel Stack permanently.

### Prompt Capture

Prompts for Parallel Stack services are captured in:
`config/hardcoded_agents.yaml`

This YAML file provides:
- Documentation and traceability
- Future migration path when services are refactored
- Prompt versioning via database if desired

Migration script: `python scripts/migrate_hardcoded_agents.py --yaml config/hardcoded_agents.yaml`

## HybridOrchestrator

Location: `app/orchestration/orchestrators/hybrid_orchestrator.py`

The HybridOrchestrator coordinates agent execution across waves:

- **Wave-based execution**: Agents in same wave run in parallel, waves run sequentially
- **Artifact passing**: Outputs from one wave become inputs for the next
- **Dual-write**: All agents write to both session artifacts and shared memory
- **Error handling**: Wave failures don't block subsequent independent waves

## Developer Team Orchestration

Location: `app/orchestration/developer_team/`

For multi-file development tasks:

- **DeveloperTeamOrchestrator**: Decomposes tasks into file-level subtasks
- **AgentSpawnerService**: Spawns ephemeral coding agents for parallel execution
- **PCI Pattern**: Parallel Context Isolation - each agent works on ONE file with scoped context
- **Max depth 1**: Spawned agents cannot spawn their own subagents

## Directory Structure

```
backend/
├── app/
│   ├── orchestration/
│   │   ├── __init__.py              # Package exports
│   │   ├── executors/
│   │   │   └── generic_executor.py  # Dynamic agent execution
│   │   ├── orchestrators/
│   │   │   └── hybrid_orchestrator.py # Wave-based coordination
│   │   ├── shared_memory/
│   │   │   ├── service.py           # Hybrid memory service
│   │   │   └── qdrant_adapter.py    # Vector storage
│   │   ├── topology/
│   │   │   ├── loader.py            # Database topology loading
│   │   │   ├── validator.py         # DAG validation
│   │   │   └── models.py            # AgentNode, AgentEdge (frozen)
│   │   ├── migration/
│   │   │   └── agent_migrator.py    # YAML to database migration
│   │   ├── artifacts/
│   │   │   ├── pool.py              # ArtifactPool for session artifacts
│   │   │   ├── schema_registry.py   # ArtifactSchemaRegistry
│   │   │   └── validators.py        # Artifact validation
│   │   ├── context_manager.py       # ContextBudgetManager
│   │   └── developer_team/
│   │       ├── orchestrator.py      # DeveloperTeamOrchestrator
│   │       ├── agent_spawner.py     # AgentSpawnerService
│   │       └── observability.py     # Agent tracing helpers
│   ├── services/
│   │   ├── control_agent_service.py # Parallel Stack
│   │   ├── product_owner_service.py # Parallel Stack
│   │   ├── analyzer_service.py      # Parallel Stack
│   │   ├── quality_judge_service.py # Parallel Stack
│   │   ├── prompt_engineer_service.py # Parallel Stack
│   │   └── tool_builder_service.py  # Parallel Stack
│   └── prompts/
│       ├── control_agent_prompt.py  # Hardcoded prompts
│       ├── product_owner_prompt.py
│       ├── analyzer_prompt.py
│       ├── quality_judge_prompt.py
│       ├── prompt_engineer_prompt.py
│       ├── tool_builder_prompt.py
│       ├── coding_agent_prompt.py
│       └── task_decomposition_prompt.py
├── config/
│   └── hardcoded_agents.yaml        # Parallel Stack definitions
└── docs/
    └── ARCHITECTURE.md              # This file
```

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Dual execution paths | Some agents need complex Python logic, others are prompt-only |
| Parallel Stack naming | Clear distinction from dynamic GenericAgentExecutor path |
| YAML prompt capture | Enables future migration without losing prompts |
| Wave-based orchestration | Natural parallelism model that respects dependencies |
| Dual-write to SharedMemory | All agents contribute to persistent knowledge base |
| Frozen Pydantic models | Prevent accidental modification during execution |
| graphlib for DAG | Zero-dependency alternative to NetworkX |
| 70/30 retrieval scoring | Balance semantic relevance with temporal recency |

## See Also

- `config/hardcoded_agents.yaml` - Parallel Stack agent definitions
- `.planning/phases/08-dynamic-orchestration-shared-memory/` - Phase 8 planning docs
- `app/models/` - Database models for agents, prompts, schemas
