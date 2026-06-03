# Refactoring: `services/` auflösen → 3 Domänen-Packages

## Ziel

Flache `services/`-Ordner (45 Dateien) auflösen in 3 Domänen-Packages:
- **`skills/`** — Skill-Lebenszyklus (Bauen, Testen, Registry, Ausführung)
- **`feedback_loop/`** — Selbstverbesserung (Analyse, Entscheidung, Improvement)
- **`orchestration/`** — erweitert um `agents/` und `execution/` Subpackages

Plus 5 Dateien in bestehende Packages integrieren. 1 Dead-Code-Datei löschen.

## Regeln

- Klassennamen bleiben gleich (nur Import-Pfade ändern)
- Jedes neue (Sub-)Package bekommt `__init__.py`
- Nach jeder Phase: `cd backend && python -c "from app.main import app"` zum Smoke-Test
- Nach allen Phasen: `cd backend && pytest` für vollständige Tests

---

## Phase 1: `skills/` Package erstellen

### 1a. Dateien verschieben

| Quelle | Ziel |
|---|---|
| `app/services/skill_team_orchestrator.py` | `app/skills/building/team_orchestrator.py` |
| `app/services/autonomous_skill_builder.py` | `app/skills/building/autonomous_builder.py` |
| `app/services/research_service.py` | `app/skills/building/research.py` |
| `app/services/dynamic_sandbox_service.py` | `app/skills/testing/docker_sandbox.py` |
| `app/services/sandbox_executor_service.py` | `app/skills/testing/sandbox_executor.py` |
| `app/services/container_image_manager.py` | `app/skills/testing/container_manager.py` |
| `app/services/semantic_validator.py` | `app/skills/testing/semantic_validator.py` |
| `app/services/package_resolver.py` | `app/skills/testing/package_resolver.py` |
| `app/services/code_validator_service.py` | `app/skills/testing/code_validator.py` |
| `app/services/skill_executor.py` | `app/skills/runtime/executor.py` |
| `app/services/skill_directory_service.py` | `app/skills/runtime/directory.py` |
| `app/services/skill_registry.py` | `app/skills/runtime/registry.py` |
| `app/services/skill_service.py` | `app/skills/runtime/crud.py` |
| `app/services/skill_validator.py` | `app/skills/runtime/validator.py` |

### 1b. Interne Imports anpassen (innerhalb der verschobenen Dateien)

**`app/skills/building/team_orchestrator.py`** (war `skill_team_orchestrator.py`):
```
from app.services.dynamic_sandbox_service → from app.skills.testing.docker_sandbox
from app.services.failure_analyzer       → from app.feedback_loop.analysis.failure_analyzer  # Phase 3!
from app.services.semantic_validator     → from app.skills.testing.semantic_validator
from app.services.code_validator_service → from app.skills.testing.code_validator
from app.services.research_service       → from app.skills.building.research
from app.services.skill_directory_service→ from app.skills.runtime.directory
from app.services.skill_registry         → from app.skills.runtime.registry
from app.services.skill_validator        → from app.skills.runtime.validator
from app.services.package_resolver       → from app.skills.testing.package_resolver
```

**`app/skills/building/autonomous_builder.py`** (war `autonomous_skill_builder.py`):
```
from app.services.dynamic_sandbox_service → from app.skills.testing.docker_sandbox
from app.services.failure_analyzer        → from app.feedback_loop.analysis.failure_analyzer  # Phase 3!
from app.services.package_resolver        → from app.skills.testing.package_resolver
from app.services.semantic_validator      → from app.skills.testing.semantic_validator
from app.services.research_service        → from app.skills.building.research
```

**`app/skills/testing/docker_sandbox.py`** (war `dynamic_sandbox_service.py`):
```
from app.services.container_image_manager → from app.skills.testing.container_manager
```

**`app/skills/testing/sandbox_executor.py`** (war `sandbox_executor_service.py`):
```
from app.services.code_validator_service  → from app.skills.testing.code_validator
from app.services.dynamic_sandbox_service → from app.skills.testing.docker_sandbox
from app.services.container_image_manager → from app.skills.testing.container_manager
```

**`app/skills/runtime/crud.py`** (war `skill_service.py`):
```
from app.services.skill_executor → from app.skills.runtime.executor
```

**`app/skills/runtime/validator.py`** (war `skill_validator.py`):
```
from app.services.dynamic_sandbox_service → from app.skills.testing.docker_sandbox
```

**`app/skills/testing/code_validator.py`** (war `code_validator_service.py`):
Keine internen Service-Imports — nur `models` und `core`.

**`app/skills/testing/semantic_validator.py`** (war `semantic_validator.py`):
Keine internen Service-Imports.

**`app/skills/testing/package_resolver.py`** (war `package_resolver.py`):
Keine internen Service-Imports.

**`app/skills/testing/container_manager.py`** (war `container_image_manager.py`):
Keine internen Service-Imports.

**`app/skills/building/research.py`** (war `research_service.py`):
Keine internen Service-Imports.

**`app/skills/runtime/executor.py`** (war `skill_executor.py`):
Keine internen Service-Imports.

**`app/skills/runtime/directory.py`** (war `skill_directory_service.py`):
Keine internen Service-Imports.

**`app/skills/runtime/registry.py`** (war `skill_registry.py`):
Keine internen Service-Imports.

### 1c. Externe Imports anpassen (andere Dateien die diese Services importieren)

**`app/api/v1/endpoints/challenges.py`**:
```
from app.services.autonomous_skill_builder import → from app.skills.building.autonomous_builder import
from app.services.dynamic_sandbox_service import  → from app.skills.testing.docker_sandbox import
from app.services.build_plan_service import       → NOCH NICHT (Phase 2)
from app.services.gap_verification_service import → NOCH NICHT (Phase 2)
from app.services.autonomous_executor_service import → NOCH NICHT (Phase 2)
```

**`app/api/v1/endpoints/skills.py`**:
```
from app.services.skill_registry import → from app.skills.runtime.registry import
```

**`app/main.py`**:
```
from app.services.skill_registry import → from app.skills.runtime.registry import
```

**`app/dependencies/evolution_loop.py`**:
```
from app.services.code_validator_service import  → from app.skills.testing.code_validator import
from app.services.sandbox_executor_service import → from app.skills.testing.sandbox_executor import
```

**`app/orchestration/executors/generic_executor.py`**:
```
from app.services.skill_executor import → from app.skills.runtime.executor import
from app.services.skill_service import  → from app.skills.runtime.crud import
```

**`app/orchestration/intervention/capability_builder.py`**:
```
from app.services.skill_team_orchestrator import  → from app.skills.building.team_orchestrator import
from app.services.dynamic_sandbox_service import  → from app.skills.testing.docker_sandbox import
```

**`app/services/__init__.py`** (temporär anpassen, in Phase 5 löschen):
```
from app.services.code_validator_service import  → from app.skills.testing.code_validator import
from app.services.sandbox_executor_service import → from app.skills.testing.sandbox_executor import
```

**`tests/conftest.py`**:
```
from app.services.skill_executor import → from app.skills.runtime.executor import
```

**`tests/test_autonomous_skill_builder.py`**:
```
from app.services.autonomous_skill_builder import → from app.skills.building.autonomous_builder import
```

**`tests/test_container_image_manager.py`**:
```
from app.services.container_image_manager import → from app.skills.testing.container_manager import
```

**`tests/test_dynamic_sandbox.py`**:
```
from app.services.dynamic_sandbox_service import → from app.skills.testing.docker_sandbox import
```

**`tests/test_skill_executor.py`**:
```
from app.services.skill_executor import → from app.skills.runtime.executor import
```

**`scripts/evaluation/gatekeeper_test.py`**:
```
from app.services.code_validator_service import → from app.skills.testing.code_validator import
```

### 1d. Hinweis: Zirkuläre Abhängigkeit

`team_orchestrator.py` und `autonomous_builder.py` importieren `failure_analyzer`, der erst in Phase 3 nach `feedback_loop/analysis/` verschoben wird. Temporär den alten Pfad `from app.services.failure_analyzer` lassen. In Phase 3 korrigieren.

---

## Phase 2: `orchestration/` erweitern (agents/ + execution/)

### 2a. Dateien verschieben

| Quelle | Ziel |
|---|---|
| `app/agents/agent_definitions.py` | `app/orchestration/agents/definitions.py` |
| `app/services/agent_spawner_service.py` | `app/orchestration/agents/spawner.py` |
| `app/services/runtime_agent_registry.py` | `app/orchestration/agents/registry.py` |
| `app/services/developer_team_orchestrator.py` | `app/orchestration/agents/developer_team.py` |
| `app/services/agent_cleanup_watchdog.py` | `app/orchestration/agents/cleanup_watchdog.py` |
| `app/services/agent_promotion.py` | `app/orchestration/agents/promotion.py` |
| `app/services/autonomous_executor_service.py` | `app/orchestration/execution/executor.py` |
| `app/services/team_assembler.py` | `app/orchestration/execution/team_assembler.py` |
| `app/services/gap_plan_service.py` | `app/orchestration/execution/gap_plan.py` |
| `app/services/gap_verification_service.py` | `app/orchestration/execution/gap_verification.py` |
| `app/services/build_plan_service.py` | `app/orchestration/execution/build_plan.py` |
| `app/services/strategy_memory.py` | `app/orchestration/execution/strategy_memory.py` |
| `app/services/topology_service.py` | `app/orchestration/topology/service.py` |

### 2b. Altes `app/agents/` Package löschen

Nach dem Verschieben von `agent_definitions.py` kann `app/agents/` gelöscht werden.

### 2c. Interne Imports anpassen (innerhalb der verschobenen Dateien)

**`app/orchestration/agents/spawner.py`** (war `agent_spawner_service.py`):
```
from app.services.runtime_agent_registry import → from app.orchestration.agents.registry import
```

**`app/orchestration/agents/developer_team.py`** (war `developer_team_orchestrator.py`):
```
from app.services.agent_spawner_service import  → from app.orchestration.agents.spawner import
from app.services.runtime_agent_registry import → from app.orchestration.agents.registry import
```

**`app/orchestration/agents/cleanup_watchdog.py`** (war `agent_cleanup_watchdog.py`):
```
from app.services.runtime_agent_registry import → from app.orchestration.agents.registry import
```

**`app/orchestration/execution/executor.py`** (war `autonomous_executor_service.py`):
```
from app.services.dynamic_sandbox_service import  → from app.skills.testing.docker_sandbox import
from app.services.container_image_manager import  → from app.skills.testing.container_manager import
from app.services.autonomous_skill_builder import → from app.skills.building.autonomous_builder import
```

**`app/orchestration/execution/gap_verification.py`** (war `gap_verification_service.py`):
```
from app.services.gap_plan_service import → from app.orchestration.execution.gap_plan import
```

**`app/orchestration/topology/service.py`** (war `topology_service.py`):
Keine internen Service-Imports.

**`app/orchestration/agents/definitions.py`** (war `agents/agent_definitions.py`):
Keine internen Service-Imports (nur stdlib/yaml).

**`app/orchestration/agents/promotion.py`**, **`app/orchestration/agents/registry.py`**,
**`app/orchestration/execution/gap_plan.py`**, **`app/orchestration/execution/build_plan.py`**,
**`app/orchestration/execution/team_assembler.py`**, **`app/orchestration/execution/strategy_memory.py`**:
Keine internen Service-Imports.

### 2d. Externe Imports anpassen

**`app/api/v1/endpoints/challenges.py`**:
```
from app.services.autonomous_executor_service import → from app.orchestration.execution.executor import
from app.services.build_plan_service import          → from app.orchestration.execution.build_plan import
from app.services.gap_verification_service import    → from app.orchestration.execution.gap_verification import
from app.services.team_assembler import              → from app.orchestration.execution.team_assembler import
from app.services.agent_promotion import             → from app.orchestration.agents.promotion import
from app.services.strategy_memory import             → from app.orchestration.execution.strategy_memory import
```

**`app/api/v1/endpoints/gap_plans.py`**:
```
from app.services.gap_plan_service import            → from app.orchestration.execution.gap_plan import
from app.services.developer_team_orchestrator import → from app.orchestration.agents.developer_team import
from app.services.agent_spawner_service import       → from app.orchestration.agents.spawner import
from app.services.runtime_agent_registry import      → from app.orchestration.agents.registry import
from app.services.agent_prompt_improver import       → NOCH NICHT (Phase 3)
```

**`app/api/v1/endpoints/topology.py`**:
```
from app.services.topology_service import → from app.orchestration.topology.service import
```

**`app/orchestration/intervention/capability_builder.py`**:
```
from app.services.developer_team_orchestrator import → from app.orchestration.agents.developer_team import
from app.services.topology_service import            → from app.orchestration.topology.service import
```

**`app/orchestration/intervention/gap_plan_executor.py`**:
```
from app.services.gap_plan_service import       → from app.orchestration.execution.gap_plan import
from app.services.agent_prompt_improver import   → NOCH NICHT (Phase 3)
from app.services.failure_analyzer import        → NOCH NICHT (Phase 3)
```

**`app/orchestration/intervention/orchestrator.py`**:
```
from app.services.gap_plan_service import            → from app.orchestration.execution.gap_plan import
from app.services.gap_verification_service import    → from app.orchestration.execution.gap_verification import
from app.services.developer_team_orchestrator import → from app.orchestration.agents.developer_team import
from app.services.agent_spawner_service import       → from app.orchestration.agents.spawner import
from app.services.runtime_agent_registry import      → from app.orchestration.agents.registry import
from app.services.agent_prompt_improver import       → NOCH NICHT (Phase 3)
from app.services.failure_analyzer import            → NOCH NICHT (Phase 3)
```

**`app/orchestration/orchestrators/hybrid_orchestrator.py`**:
```
from app.services.autonomous_executor_service import → from app.orchestration.execution.executor import
from app.services.developer_team_orchestrator import → from app.orchestration.agents.developer_team import
from app.services.agent_spawner_service import       → from app.orchestration.agents.spawner import
from app.services.runtime_agent_registry import      → from app.orchestration.agents.registry import
from app.services.telemetry_service import           → NOCH NICHT (Phase 4)
from app.services.agent_prompt_improver import       → NOCH NICHT (Phase 3)
```

**`app/orchestration/topology/loader.py`**:
```
from app.services.ab_test_service import → NOCH NICHT (Phase 3)
```

**`app/prompts/analyzer_prompt.py`**:
```
from app.agents.agent_definitions import → from app.orchestration.agents.definitions import
```

**`app/prompts/control_agent_prompt.py`**:
```
from app.agents.agent_definitions import → from app.orchestration.agents.definitions import
```

**`app/prompts/product_owner_prompt.py`**:
```
from app.agents.agent_definitions import → from app.orchestration.agents.definitions import
```

**`app/prompts/prompt_engineer_prompt.py`**:
```
from app.agents.agent_definitions import → from app.orchestration.agents.definitions import
```

**`app/prompts/quality_judge_prompt.py`**:
```
from app.agents.agent_definitions import → from app.orchestration.agents.definitions import
```

**`app/prompts/tool_builder_prompt.py`**:
```
from app.agents.agent_definitions import → from app.orchestration.agents.definitions import
```

**`scripts/seed_agents.py`**:
```
from app.agents.agent_definitions import → from app.orchestration.agents.definitions import
```

**`app/services/__init__.py`** (temporär, in Phase 5 löschen):
```
from app.services.runtime_agent_registry import      → from app.orchestration.agents.registry import
from app.services.agent_spawner_service import       → from app.orchestration.agents.spawner import
from app.services.agent_cleanup_watchdog import      → from app.orchestration.agents.cleanup_watchdog import
from app.services.developer_team_orchestrator import → from app.orchestration.agents.developer_team import
```

---

## Phase 3: `feedback_loop/` Package erstellen

### 3a. Dateien verschieben

| Quelle | Ziel |
|---|---|
| `app/services/analysis_pipeline.py` | `app/feedback_loop/analysis/pipeline.py` |
| `app/services/analyzer_service.py` | `app/feedback_loop/analysis/analyzer.py` |
| `app/services/failure_analyzer.py` | `app/feedback_loop/analysis/failure_analyzer.py` |
| `app/services/statistical_analyzer.py` | `app/feedback_loop/analysis/statistical.py` |
| `app/services/control_agent_service.py` | `app/feedback_loop/decisions/control_agent.py` |
| `app/services/product_owner_service.py` | `app/feedback_loop/decisions/product_owner.py` |
| `app/services/quality_judge_service.py` | `app/feedback_loop/decisions/quality_judge.py` |
| `app/services/improvement_orchestrator.py` | `app/feedback_loop/improvement/orchestrator.py` |
| `app/services/agent_prompt_improver.py` | `app/feedback_loop/improvement/prompt_improver.py` |
| `app/services/prompt_engineer_service.py` | `app/feedback_loop/improvement/prompt_engineer.py` |
| `app/services/tool_builder_service.py` | `app/feedback_loop/improvement/tool_builder.py` |
| `app/services/ab_test_service.py` | `app/feedback_loop/improvement/ab_testing.py` |
| `app/services/rollback_service.py` | `app/feedback_loop/improvement/rollback.py` |
| `app/services/evolution_loop_service.py` | `app/feedback_loop/loop.py` |

### 3b. Interne Imports anpassen (innerhalb der verschobenen Dateien)

**`app/feedback_loop/loop.py`** (war `evolution_loop_service.py`):
```
from app.services.analysis_pipeline import      → from app.feedback_loop.analysis.pipeline import
from app.services.control_agent_service import  → from app.feedback_loop.decisions.control_agent import
from app.services.improvement_orchestrator import → from app.feedback_loop.improvement.orchestrator import
```

**`app/feedback_loop/analysis/pipeline.py`** (war `analysis_pipeline.py`):
```
from app.services.analyzer_service import       → from app.feedback_loop.analysis.analyzer import
from app.services.product_owner_service import  → from app.feedback_loop.decisions.product_owner import
from app.services.telemetry_service import      → from app.core.telemetry import  # Phase 4!
```

**`app/feedback_loop/improvement/orchestrator.py`** (war `improvement_orchestrator.py`):
```
from app.services.prompt_engineer_service import  → from app.feedback_loop.improvement.prompt_engineer import
from app.services.ab_test_service import          → from app.feedback_loop.improvement.ab_testing import
from app.services.tool_builder_service import     → from app.feedback_loop.improvement.tool_builder import
from app.services.sandbox_executor_service import → from app.skills.testing.sandbox_executor import
```

**`app/feedback_loop/improvement/ab_testing.py`** (war `ab_test_service.py`):
```
from app.services.quality_judge_service import → from app.feedback_loop.decisions.quality_judge import
from app.services.rollback_service import      → from app.feedback_loop.improvement.rollback import
from app.services.statistical_analyzer import  → from app.feedback_loop.analysis.statistical import
```

**`app/feedback_loop/improvement/rollback.py`** (war `rollback_service.py`):
```
from app.services.version_service import → from app.core.versioning import  # Phase 4!
```

**`app/feedback_loop/improvement/tool_builder.py`** (war `tool_builder_service.py`):
```
from app.services.code_validator_service import → from app.skills.testing.code_validator import
```

**`app/feedback_loop/improvement/prompt_improver.py`** (war `agent_prompt_improver.py`):
```
from app.services.topology_service import → from app.orchestration.topology.service import
```

**`app/feedback_loop/analysis/analyzer.py`**, **`app/feedback_loop/decisions/control_agent.py`**,
**`app/feedback_loop/decisions/product_owner.py`**, **`app/feedback_loop/decisions/quality_judge.py`**,
**`app/feedback_loop/improvement/prompt_engineer.py`**, **`app/feedback_loop/analysis/statistical.py`**,
**`app/feedback_loop/analysis/failure_analyzer.py`**:
Keine internen Service-Imports.

### 3c. Externe Imports anpassen

**`app/api/v1/endpoints/evolution.py`**:
```
from app.services.evolution_loop_service import → from app.feedback_loop.loop import
```

**`app/api/v1/endpoints/gap_plans.py`**:
```
from app.services.agent_prompt_improver import → from app.feedback_loop.improvement.prompt_improver import
```

**`app/dependencies/evolution_loop.py`**:
```
from app.services.ab_test_service import         → from app.feedback_loop.improvement.ab_testing import
from app.services.analysis_pipeline import       → from app.feedback_loop.analysis.pipeline import
from app.services.analyzer_service import        → from app.feedback_loop.analysis.analyzer import
from app.services.control_agent_service import   → from app.feedback_loop.decisions.control_agent import
from app.services.evolution_loop_service import  → from app.feedback_loop.loop import
from app.services.improvement_orchestrator import → from app.feedback_loop.improvement.orchestrator import
from app.services.product_owner_service import   → from app.feedback_loop.decisions.product_owner import
from app.services.prompt_engineer_service import → from app.feedback_loop.improvement.prompt_engineer import
from app.services.quality_judge_service import   → from app.feedback_loop.decisions.quality_judge import
from app.services.rollback_service import        → from app.feedback_loop.improvement.rollback import
from app.services.statistical_analyzer import    → from app.feedback_loop.analysis.statistical import
from app.services.tool_builder_service import    → from app.feedback_loop.improvement.tool_builder import
from app.services.version_service import         → from app.core.versioning import  # Phase 4!
```

**`app/orchestration/intervention/gap_plan_executor.py`**:
```
from app.services.agent_prompt_improver import → from app.feedback_loop.improvement.prompt_improver import
from app.services.failure_analyzer import      → from app.feedback_loop.analysis.failure_analyzer import
```

**`app/orchestration/intervention/orchestrator.py`**:
```
from app.services.agent_prompt_improver import → from app.feedback_loop.improvement.prompt_improver import
from app.services.failure_analyzer import      → from app.feedback_loop.analysis.failure_analyzer import
```

**`app/orchestration/orchestrators/hybrid_orchestrator.py`**:
```
from app.services.agent_prompt_improver import → from app.feedback_loop.improvement.prompt_improver import
```

**`app/orchestration/topology/loader.py`**:
```
from app.services.ab_test_service import → from app.feedback_loop.improvement.ab_testing import
```

**Aufgeschobene Cross-Domain-Imports aus Phase 1 jetzt korrigieren:**

**`app/skills/building/team_orchestrator.py`**:
```
from app.services.failure_analyzer import → from app.feedback_loop.analysis.failure_analyzer import
```

**`app/skills/building/autonomous_builder.py`**:
```
from app.services.failure_analyzer import → from app.feedback_loop.analysis.failure_analyzer import
```

**`app/services/__init__.py`** (temporär, in Phase 5 löschen):
```
from app.services.prompt_engineer_service import  → from app.feedback_loop.improvement.prompt_engineer import
from app.services.improvement_orchestrator import → from app.feedback_loop.improvement.orchestrator import
from app.services.tool_builder_service import     → from app.feedback_loop.improvement.tool_builder import
```

**`tests/test_evolution_loop.py`**:
```
from app.services.evolution_loop_service import → from app.feedback_loop.loop import
```

---

## Phase 4: Restliche Services in bestehende Packages integrieren

### 4a. Dateien verschieben

| Quelle | Ziel |
|---|---|
| `app/services/telemetry_service.py` | `app/core/telemetry.py` |
| `app/services/version_service.py` | `app/core/versioning.py` |
| `app/services/template_service.py` | `app/adapters/templates.py` |

### 4b. Externe Imports anpassen

**`app/dependencies/dependencies.py`**:
```
from app.services.telemetry_service import → from app.core.telemetry import
from app.services.template_service import  → from app.adapters.templates import
```

**`app/dependencies/evolution_loop.py`**:
```
from app.services.telemetry_service import → from app.core.telemetry import
from app.services.version_service import   → from app.core.versioning import
```

**`app/api/v1/endpoints/templates.py`**:
```
from app.services.template_service import → from app.adapters.templates import
```

**`app/orchestration/orchestrators/hybrid_orchestrator.py`**:
```
from app.services.telemetry_service import → from app.core.telemetry import
```

**Aufgeschobene Imports aus Phase 3 korrigieren:**

**`app/feedback_loop/analysis/pipeline.py`**:
```
from app.services.telemetry_service import → from app.core.telemetry import
```

**`app/feedback_loop/improvement/rollback.py`**:
```
from app.services.version_service import → from app.core.versioning import
```

---

## Phase 5: Aufräumen

### 5a. Dead Code löschen

```
LÖSCHEN: app/services/agent_service.py     (nie importiert)
```

### 5b. `services/` Package entfernen

Alle Dateien sollten jetzt verschoben sein. Prüfen:

```bash
# Sollte nur __init__.py und __pycache__ zeigen
ls app/services/

# Sollte 0 Treffer liefern
grep -rn "from app\.services\." --include="*.py" | grep -v __pycache__

# Sollte 0 Treffer liefern
grep -rn "from app\.agents\." --include="*.py" | grep -v __pycache__
```

Dann löschen:
```
LÖSCHEN: app/services/              (gesamtes Verzeichnis)
LÖSCHEN: app/agents/                (gesamtes Verzeichnis, wurde nach orchestration/agents/ verschoben)
```

### 5c. Validierung

```bash
cd backend

# Import-Check
python -c "from app.main import app; print('OK')"

# Vollständige Tests
pytest

# Keine verwaisten Imports
grep -rn "from app\.services\." --include="*.py" | grep -v __pycache__
grep -rn "from app\.agents\." --include="*.py" | grep -v __pycache__
```

---

## Ergebnis: Vorher → Nachher

### Vorher
```
app/
  agents/                  (2 Dateien)
  services/                (45 Dateien, flach)
  orchestration/           (38 Dateien, gut strukturiert)
  core/                    (11 Dateien)
  ...
```

### Nachher
```
app/
  skills/                  (14 Dateien in 3 Subpackages)
    building/              (3)  team_orchestrator, autonomous_builder, research
    testing/               (6)  docker_sandbox, sandbox_executor, container_manager,
                                semantic_validator, package_resolver, code_validator
    runtime/               (5)  executor, directory, registry, crud, validator

  orchestration/           (51 Dateien in 13 Subpackages)
    agents/                (6)  definitions, spawner, registry, developer_team,
                                cleanup_watchdog, promotion
    execution/             (6)  executor, team_assembler, gap_plan, gap_verification,
                                build_plan, strategy_memory
    topology/              (4)  service, loader, models, validator
    analysis/              (6)  bestehend
    artifacts/             (5)  bestehend
    executors/             (3)  bestehend
    intervention/          (7)  bestehend
    orchestrators/         (2)  bestehend
    shared_memory/         (3)  bestehend
    verification/          (3)  bestehend
    migration/             (2)  bestehend
    context_manager.py

  feedback_loop/           (14 Dateien in 3 Subpackages + 1 Root)
    analysis/              (4)  pipeline, analyzer, failure_analyzer, statistical
    decisions/             (3)  control_agent, product_owner, quality_judge
    improvement/           (6)  orchestrator, prompt_improver, prompt_engineer,
                                tool_builder, ab_testing, rollback
    loop.py

  core/                    (13 Dateien, +2)
    telemetry.py           NEU
    versioning.py          NEU

  adapters/                (6 Dateien, +1)
    templates.py           NEU

  GELÖSCHT:
    services/              (komplett)
    agents/                (nach orchestration/agents/)
```
