"""Hybrid Orchestrator combining Shared Memory + Artifact Passing."""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.orchestration.topology.loader import TopologyLoader
from app.orchestration.topology.models import Topology, AgentNode
from app.orchestration.artifacts.pool import ArtifactPool
from app.orchestration.shared_memory.service import SharedMemoryService
from app.orchestration.executors.generic_executor import GenericAgentExecutor
from app.orchestration.context_manager import ContextBudgetManager
from app.models.sql.agent_event_models import AgentExecutionEvent
from app.models.sql.execution_models import Execution

logger = logging.getLogger(__name__)


class FailureType(str, Enum):
    """Classification of agent execution failures for retry routing."""
    LLM_TRANSIENT = "llm_transient"
    LLM_REFUSAL = "llm_refusal"
    ARTIFACT_VALIDATION = "artifact_validation"
    TOOL_ERROR = "tool_error"
    BAD_INPUT = "bad_input"
    UNKNOWN = "unknown"


@dataclass
class AgentFailureRecord:
    """Tracks a single agent failure for retry decisions."""
    agent_id: str
    agent_name: str
    wave: int
    failure_type: FailureType
    error_message: str
    retries_attempted: int = 0
    resolved: bool = False
    produces_artifacts: list[str] = field(default_factory=list)

# Type alias for session factory
SessionFactory = Callable[[], AsyncSession]


class HybridOrchestrator:
    """
    Orchestrator combining Shared Memory + Artifact Passing.

    Key behaviors:
    - Loads topology from database (dynamic)
    - Executes agents in wave order (parallel within waves)
    - Artifacts for intra-run communication
    - Shared memory for cross-run learning
    - Context budget enforced for LLM calls
    - Skills injected from TopologyLoader cache
    """

    def __init__(
        self,
        db: AsyncSession,
        llm_client: Any,
        topology_loader: Optional[TopologyLoader] = None,
        shared_memory: Optional[SharedMemoryService] = None,
        context_manager: Optional[ContextBudgetManager] = None,
        session_factory: Optional[SessionFactory] = None,
        embedding_fn: Optional[Any] = None,
    ):
        """
        Initialize hybrid orchestrator.

        Args:
            db: Database session (for backward compatibility)
            llm_client: LLM client for agent execution
            topology_loader: Topology loader (creates if not provided)
            shared_memory: Shared memory service (creates if not provided)
            context_manager: Context budget manager
            session_factory: Factory for creating new sessions (preferred over db)
            embedding_fn: Async function(text) -> embedding vector for SharedMemory
        """
        self.db = db
        self.llm_client = llm_client
        self.topology_loader = topology_loader
        self.shared_memory = shared_memory
        self.context_manager = context_manager or ContextBudgetManager()
        self._session_factory = session_factory
        self._embedding_fn = embedding_fn
        self._db_lock = asyncio.Lock()  # Lock for serializing DB operations

        self._artifact_pool: Optional[ArtifactPool] = None
        self._executor: Optional[GenericAgentExecutor] = None
        self._execution_id: Optional[str] = None
        self._current_wave: int = 0
        self._project_id: str = "default"
        self._challenge_id: Optional[str] = None

        # Self-healing retry state
        self._failure_tracker: dict[str, AgentFailureRecord] = {}
        self._max_retries_per_agent = 2
        self._prompt_improver: Optional[Any] = None
        self._capability_builder: Optional[Any] = None

    async def initialize(self) -> None:
        """Initialize orchestrator components."""
        # Create topology loader if not provided
        if not self.topology_loader:
            self.topology_loader = TopologyLoader(self._session_factory)
            await self.topology_loader.load()

        # Create shared memory if not provided (optional - execution works without it)
        if not self.shared_memory:
            try:
                from app.orchestration.shared_memory.qdrant_adapter import SharedMemoryQdrantAdapter
                from qdrant_client import QdrantClient

                # Note: In production, inject Qdrant client from config
                qdrant_client = QdrantClient(url="http://localhost:6333", timeout=5)
                qdrant_adapter = SharedMemoryQdrantAdapter(qdrant_client)
                await qdrant_adapter.ensure_collections()

                self.shared_memory = SharedMemoryService(
                    db=self.db,
                    qdrant_adapter=qdrant_adapter,
                    context_manager=self.context_manager,
                    embedding_fn=self._embedding_fn,
                )
                logger.info("Shared memory initialized with Qdrant")
            except Exception as e:
                logger.warning(f"Shared memory unavailable (Qdrant not running?): {e}")
                self.shared_memory = None

        logger.info("HybridOrchestrator initialized")

    async def execute(
        self,
        input_data: Optional[dict] = None,
        execution_id: Optional[str] = None,
        project_id: str = "default",
        challenge_id: Optional[str] = None
    ) -> dict[str, Any]:
        """
        Execute full agent workflow.

        1. Load/validate topology
        2. Create artifact pool for session
        3. Execute agents in wave order
        4. Collect results
        5. Clear session artifacts

        Args:
            input_data: Initial input for first agent(s)
            execution_id: Execution ID (auto-generated if not provided)
            project_id: Project scope for this execution
            challenge_id: Associated challenge ID if from challenge execution

        Returns:
            Execution results with outputs from all agents
        """
        self._execution_id = execution_id or str(uuid4())
        self._project_id = project_id
        self._challenge_id = challenge_id
        self._failure_tracker = {}
        start_time = datetime.now(timezone.utc)

        logger.info(f"Starting execution: {self._execution_id}")

        # Create execution record in database
        await self._create_execution_record(input_data)

        # 1. Reload topology (per CONTEXT: between runs only)
        topology, validation = await self.topology_loader.reload()
        if not validation.is_valid:
            error_msg = f"Invalid topology: {validation.errors}"
            await self._update_execution_record(
                status="failed",
                error=error_msg,
                completed_at=datetime.now(timezone.utc)
            )
            return {
                "success": False,
                "error": error_msg,
                "execution_id": self._execution_id
            }

        # 2. Create artifact pool for this session
        self._artifact_pool = ArtifactPool(execution_id=self._execution_id)

        # 3. Create sandbox executor for secure skill execution
        sandbox_executor = await self._create_sandbox_executor()

        # 4. Create executor with topology_loader for skill injection
        # Create intervention orchestrator for self-healing (if enabled)
        intervention = None
        from app.core.config import settings
        if settings.intra_execution_self_healing_enabled and self.db:
            try:
                from app.orchestration.intervention.orchestrator import create_intervention_orchestrator
                intervention = await create_intervention_orchestrator(
                    db=self.db,
                    topology_loader=self.topology_loader,
                )
            except Exception as e:
                logger.warning(f"Could not create intervention orchestrator for self-healing: {e}")

        self._executor = GenericAgentExecutor(
            llm_client=self.llm_client,
            artifact_pool=self._artifact_pool,
            shared_memory=self.shared_memory,
            context_manager=self.context_manager,
            topology_loader=self.topology_loader,  # Pass for skill injection
            db=self.db,  # Pass for auto-creating skills
            sandbox_executor=sandbox_executor,  # Pass for secure skill execution
            intervention_orchestrator=intervention,  # Pass for self-healing
        )

        # 5. Store input for all waves (transcript should be available to all agents)
        self._original_input = input_data

        # 6. Execute in waves
        results: dict[str, Any] = {}
        waves = validation.execution_waves or [[]]

        for wave_idx, wave_agents in enumerate(waves):
            logger.info(f"Executing wave {wave_idx + 1}/{len(waves)}: {wave_agents}")

            wave_results = await self._execute_wave(
                agent_ids=wave_agents,
                topology=topology,
                input_data=input_data,  # Pass to ALL waves, not just wave 1
                wave_number=wave_idx + 1
            )

            results[f"wave_{wave_idx + 1}"] = wave_results

            # Self-healing: repair and retry failed agents before next wave
            retry_results = await self._repair_and_retry(
                topology, input_data, wave_number=wave_idx + 1,
            )
            if retry_results:
                results[f"wave_{wave_idx + 1}_retries"] = retry_results
                for name, r in retry_results.items():
                    if isinstance(r, dict) and r.get("success"):
                        wave_results[name] = r

        # 7. Clear session artifacts
        await self._artifact_pool.clear()

        end_time = datetime.now(timezone.utc)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        # Derive success from actual agent results
        unresolved = [f for f in self._failure_tracker.values() if not f.resolved]
        overall_success = len(unresolved) == 0

        # Aggregate token usage across all agents and waves
        total_tokens = 0
        total_input = 0
        total_output = 0
        for wave_key, wave_results in results.items():
            if isinstance(wave_results, dict):
                for agent_result in wave_results.values():
                    if isinstance(agent_result, dict):
                        total_tokens += agent_result.get("tokens_total", 0) or 0
                        total_input += agent_result.get("tokens_input", 0) or 0
                        total_output += agent_result.get("tokens_output", 0) or 0

        result = {
            "success": overall_success,
            "execution_id": self._execution_id,
            "results": results,
            "duration_ms": duration_ms,
            "waves_executed": len(waves),
            "agents_executed": sum(len(w) for w in waves),
            "tokens_total": total_tokens,
            "tokens_input": total_input,
            "tokens_output": total_output,
            "failed_agents": [
                {
                    "agent_id": f.agent_id,
                    "agent_name": f.agent_name,
                    "failure_type": f.failure_type.value,
                    "error": f.error_message,
                    "retries_attempted": f.retries_attempted,
                }
                for f in unresolved
            ],
        }

        # Update execution record with honest status
        await self._update_execution_record(
            status="completed" if overall_success else "failed",
            results=results,
            error="; ".join(f.error_message for f in unresolved)[:500] if unresolved else None,
            waves_executed=len(waves),
            agents_executed=sum(len(w) for w in waves),
            duration_ms=duration_ms,
            completed_at=end_time,
        )

        # Persist execution outcome to SharedMemory for cross-run learning
        await self._persist_execution_learnings(
            results=results,
            success=overall_success,
            duration_ms=duration_ms,
            input_data=input_data,
        )

        # Sprint 1: Autonomous Evolution Loop — fire-and-forget.
        # Runs analyze -> prioritize -> decide -> improve in a background task
        # with its own isolated DB session. Must never break the main execution.
        _primary_agent_id = waves[0][0] if waves and waves[0] else "unknown"
        try:
            from app.core.config import settings as _settings
            if _settings.autonomous_evolution_enabled and self._execution_id:
                task = asyncio.create_task(
                    _run_evolution_loop_safely(
                        execution_id=self._execution_id,
                        agent_id=_primary_agent_id,
                        input_data=self._original_input or {},
                        tokens_input=total_input,
                        tokens_output=total_output,
                        outcome="success" if overall_success else "failed",
                        error_message=(
                            "; ".join(f.error_message for f in unresolved)[:500]
                            if unresolved else None
                        ),
                    )
                )
                task.add_done_callback(
                    lambda t, eid=self._execution_id: _log_evolution_task_exception(t, eid)
                )
        except Exception as e:
            # Scheduling itself failed — log and continue, never block return.
            logger.warning(f"Failed to schedule evolution loop: {e}")

        return result

    async def _execute_wave(
        self,
        agent_ids: list[str],
        topology: Topology,
        input_data: Optional[dict],
        wave_number: int = 1
    ) -> dict[str, Any]:
        """Execute all agents in a wave (parallel) with event emission."""
        self._current_wave = wave_number
        tasks = []
        wave_results: dict[str, Any] = {}

        # Pre-fetch all prompts before parallel execution to avoid
        # concurrent DB session access (greenlet_spawn errors)
        agents_to_run: list[AgentNode] = []
        for agent_id in agent_ids:
            agent = topology.get_agent(agent_id)
            if not agent:
                logger.warning(f"Agent {agent_id} not found in topology")
                continue

            # Check if dependencies are satisfied before dispatching
            skip_reason = await self._should_skip_agent(agent, wave_number)
            if skip_reason:
                logger.warning(f"Skipping {agent.name}: {skip_reason}")
                await self._emit_agent_event(
                    event_type="agent_error", agent_id=agent_id,
                    agent_name=agent.name, wave=wave_number,
                    error=f"Skipped: {skip_reason}",
                )
                wave_results[agent.name] = {
                    "success": False, "skipped": True,
                    "error": skip_reason, "agent_id": agent_id,
                }
                self._failure_tracker[agent_id] = AgentFailureRecord(
                    agent_id=agent_id, agent_name=agent.name, wave=wave_number,
                    failure_type=FailureType.BAD_INPUT, error_message=skip_reason,
                    produces_artifacts=list(agent.produces_artifacts),
                )
                continue

            agents_to_run.append(agent)

        # Prefetch prompts sequentially (safe DB access)
        prompt_cache = await self._prefetch_prompts(agents_to_run)

        for agent in agents_to_run:
            # Emit agent_start event
            await self._emit_agent_event(
                event_type="agent_start",
                agent_id=agent.agent_id,
                agent_name=agent.name,
                wave=wave_number
            )

            task = self._execute_agent_with_events(
                agent, input_data, wave_number, prompt_cache=prompt_cache
            )
            tasks.append((agent.name, agent.agent_id, task))

        # Execute in parallel
        if tasks:
            agent_tasks = [t for _, _, t in tasks]
            results = await asyncio.gather(*agent_tasks, return_exceptions=True)

            for (agent_name, agent_id, _), result in zip(tasks, results):
                if isinstance(result, Exception):
                    result_dict = {
                        "success": False,
                        "error": str(result),
                        "failure_type": "llm_error",
                        "agent_id": agent_id,
                    }
                    wave_results[agent_name] = result_dict
                    logger.warning(
                        f"Wave {wave_number} agent '{agent_name}' raised exception: {result}"
                    )
                else:
                    if isinstance(result, dict):
                        result["agent_id"] = agent_id
                        result["agent_name"] = agent_name
                    wave_results[agent_name] = result
                    result_dict = result if isinstance(result, dict) else {}
                    logger.info(
                        f"Wave {wave_number} agent '{agent_name}' completed: "
                        f"success={result_dict.get('success')}, "
                        f"skipped={result_dict.get('skipped', False)}, "
                        f"result_len={len(str(result_dict.get('result', '')))}"
                    )

                # Track failures
                is_failure = (
                    isinstance(result, Exception)
                    or (isinstance(result, dict) and not result.get("success", True))
                )
                if is_failure:
                    agent_node = topology.get_agent(agent_id)
                    self._failure_tracker[agent_id] = AgentFailureRecord(
                        agent_id=agent_id, agent_name=agent_name, wave=wave_number,
                        failure_type=self._classify_failure(result_dict),
                        error_message=str(result_dict.get("error", result)),
                        produces_artifacts=list(agent_node.produces_artifacts) if agent_node else [],
                    )

        return wave_results

    async def _execute_agent_with_events(
        self,
        agent: AgentNode,
        input_data: Optional[dict],
        wave_number: int,
        prompt_cache: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Execute agent and emit completion/error events."""
        try:
            result = await self._execute_agent(agent, input_data, prompt_cache=prompt_cache)

            # Emit agent_complete event
            await self._emit_agent_event(
                event_type="agent_complete",
                agent_id=agent.agent_id,
                agent_name=agent.name,
                wave=wave_number,
                data={
                    "tokens_total": result.get("tokens_total"),
                    "latency_ms": result.get("latency_ms"),
                }
            )

            return result
        except Exception as e:
            # Emit agent_error event
            await self._emit_agent_event(
                event_type="agent_error",
                agent_id=agent.agent_id,
                agent_name=agent.name,
                wave=wave_number,
                error=str(e)
            )
            raise

    async def _prefetch_prompts(self, agents: list[AgentNode]) -> dict[str, str]:
        """Pre-load all prompts for a wave before parallel execution."""
        prompt_cache: dict[str, str] = {}
        for agent in agents:
            if agent.prompt_id and agent.prompt_id not in prompt_cache:
                content = await self._get_prompt(agent.prompt_id)
                if content:
                    prompt_cache[agent.prompt_id] = content
        return prompt_cache

    async def _execute_agent(
        self,
        agent: AgentNode,
        input_data: Optional[dict],
        prompt_cache: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Execute a single agent."""
        # Use pre-fetched prompt if available, otherwise fetch (with lock)
        prompt_content = None
        if prompt_cache and agent.prompt_id:
            prompt_content = prompt_cache.get(agent.prompt_id)
        if not prompt_content:
            prompt_content = await self._get_prompt(agent.prompt_id)
        if not prompt_content:
            prompt_content = f"You are {agent.name}. Execute your task."

        return await self._executor.execute(
            agent=agent,
            prompt_content=prompt_content,
            execution_id=self._execution_id,
            input_data=input_data,
            project_id=self._project_id
        )

    # --- Self-healing retry infrastructure ---

    def _classify_failure(self, result: dict) -> FailureType:
        """Classify agent failure for retry routing."""
        ft = result.get("failure_type", "")
        error = str(result.get("error", "")).lower()

        if ft == "artifact_validation":
            return FailureType.ARTIFACT_VALIDATION
        if ft == "agent_refusal" or result.get("skipped"):
            return FailureType.LLM_REFUSAL
        if ft == "tool_error":
            return FailureType.TOOL_ERROR
        if ft == "llm_error":
            if any(kw in error for kw in ("timeout", "rate_limit", "rate limit", "503", "429")):
                return FailureType.LLM_TRANSIENT
        return FailureType.UNKNOWN

    async def _should_skip_agent(self, agent: AgentNode, wave_number: int = 1) -> Optional[str]:
        """Check if agent should be skipped due to failed dependencies or missing artifacts."""
        for consumed_type in agent.consumes_artifacts:
            for record in self._failure_tracker.values():
                if consumed_type in record.produces_artifacts and not record.resolved:
                    return (
                        f"Artifact '{consumed_type}' unavailable: "
                        f"agent '{record.agent_name}' failed"
                    )
            # Pool-Check only for waves > 1 (wave 1 artifacts don't exist yet)
            if wave_number > 1:
                artifacts = await self._artifact_pool.read([consumed_type])
                if not artifacts:
                    return f"Artifact '{consumed_type}' not found in pool"
        return None

    def _get_prompt_improver(self) -> Any:
        """Lazy-init AgentPromptImprover for retry repairs."""
        if not self._prompt_improver:
            from app.services.agent_prompt_improver import AgentPromptImprover

            async def llm_wrapper(messages: list[dict]) -> str:
                response = await self.llm_client.chat(messages)
                return response.content

            self._prompt_improver = AgentPromptImprover(self._session_factory, llm_fn=llm_wrapper)
        return self._prompt_improver

    def _get_capability_builder(self) -> Any:
        """Lazy-init CapabilityBuilder for skill repair."""
        if not self._capability_builder:
            from app.orchestration.intervention.builder import CapabilityBuilder
            from app.services.developer_team_orchestrator import DeveloperTeamOrchestrator
            from app.services.agent_spawner_service import AgentSpawnerService
            from app.services.runtime_agent_registry import RuntimeAgentRegistry

            registry = RuntimeAgentRegistry(max_concurrent_agents=5)
            spawner = AgentSpawnerService(registry, self.llm_client)
            developer_team = DeveloperTeamOrchestrator(
                spawner=spawner, llm_client=self.llm_client, registry=registry,
            )
            self._capability_builder = CapabilityBuilder(developer_team, self._session_factory)
        return self._capability_builder

    async def _repair_and_retry(
        self,
        topology: Topology,
        input_data: Optional[dict],
        wave_number: int,
    ) -> dict[str, Any]:
        """Attempt to repair and retry failed agents from a wave."""
        retryable = {
            aid: rec for aid, rec in self._failure_tracker.items()
            if rec.wave == wave_number
            and not rec.resolved
            and rec.failure_type != FailureType.BAD_INPUT
            and rec.retries_attempted < self._max_retries_per_agent
            # UNKNOWN gets only 1 retry
            and not (rec.failure_type == FailureType.UNKNOWN and rec.retries_attempted >= 1)
        }

        if not retryable:
            return {}

        logger.info(
            f"Wave {wave_number} self-healing: {len(retryable)} agents to retry: "
            f"{[r.agent_name for r in retryable.values()]}"
        )

        retry_results: dict[str, Any] = {}

        # Prefetch prompts for retryable agents to avoid greenlet errors
        retry_agents = [topology.get_agent(aid) for aid in retryable if topology.get_agent(aid)]
        prompt_cache = await self._prefetch_prompts(retry_agents)

        for agent_id, record in retryable.items():
            agent_node = topology.get_agent(agent_id)
            if not agent_node:
                continue

            record.retries_attempted += 1
            repair_type = "none"

            # Apply repair strategy based on failure type
            try:
                if record.failure_type in (FailureType.LLM_REFUSAL, FailureType.ARTIFACT_VALIDATION):
                    repair_type = "prompt_improvement"
                    improver = self._get_prompt_improver()
                    capability = agent_node.capabilities[0] if agent_node.capabilities else agent_node.name
                    build_result = await improver.improve(
                        affected_capability=capability,
                        gap_description=record.error_message,
                        challenge_context=json.dumps(input_data or {})[:500],
                    )
                    if build_result.success:
                        logger.info(f"Prompt improved for {record.agent_name}: {build_result.artifact_id}")
                    else:
                        logger.warning(f"Prompt improvement failed for {record.agent_name}: {build_result.failure_reason}")

                elif record.failure_type == FailureType.TOOL_ERROR:
                    repair_type = "skill_build"
                    from app.models.schemas.analysis_schemas import CapabilityGap, GapType, GapSeverity
                    gap = CapabilityGap(
                        gap_type=GapType.MISSING_SKILL,
                        severity=GapSeverity.CRITICAL,
                        description=record.error_message[:100],
                        affected_capability=agent_node.capabilities[0] if agent_node.capabilities else agent_node.name,
                    )
                    builder = self._get_capability_builder()
                    build_result = await builder.build_for_gap(
                        gap=gap,
                        challenge_text=json.dumps(input_data or {})[:500],
                        attempt_number=record.retries_attempted,
                        previous_failures=[record.error_message],
                    )
                    if build_result.success:
                        logger.info(f"Skill built for {record.agent_name}: {build_result.artifact_id}")
                        await self.topology_loader.reload()
                    else:
                        logger.warning(f"Skill build failed for {record.agent_name}: {build_result.failure_reason}")

                elif record.failure_type == FailureType.LLM_TRANSIENT:
                    repair_type = "simple_retry"

                else:
                    repair_type = "simple_retry"

            except Exception as e:
                logger.error(f"Repair failed for {record.agent_name}: {e}")

            # Retry the agent
            await self._emit_agent_event(
                event_type="agent_retry", agent_id=agent_id,
                agent_name=record.agent_name, wave=wave_number,
                data={"attempt": record.retries_attempted, "repair": repair_type},
            )

            try:
                result = await self._execute_agent_with_events(agent_node, input_data, wave_number, prompt_cache=prompt_cache)

                if isinstance(result, dict) and result.get("success"):
                    record.resolved = True
                    logger.info(f"Retry succeeded for {record.agent_name} (repair: {repair_type})")
                else:
                    # Update failure record for potential next retry
                    result_dict = result if isinstance(result, dict) else {"error": str(result)}
                    record.failure_type = self._classify_failure(result_dict)
                    record.error_message = str(result_dict.get("error", result))
                    logger.warning(f"Retry failed for {record.agent_name}: {record.error_message[:100]}")

                retry_results[record.agent_name] = result

            except Exception as e:
                logger.error(f"Retry execution failed for {record.agent_name}: {e}")
                record.error_message = str(e)
                retry_results[record.agent_name] = {"success": False, "error": str(e)}

        return retry_results

    async def _get_prompt(self, prompt_id: Optional[str]) -> Optional[str]:
        """Get prompt content from database. Uses lock to prevent concurrent session access."""
        if not prompt_id:
            return None

        from app.models.sql.versioned_models import Prompt

        async with self._db_lock:
            result = await self.db.execute(
                select(Prompt).where(Prompt.id == prompt_id)
            )
            prompt = result.scalar_one_or_none()
            return prompt.content if prompt else None

    async def _persist_execution_learnings(
        self,
        results: dict[str, Any],
        success: bool,
        duration_ms: int,
        input_data: Optional[dict],
    ) -> None:
        """
        Persist execution outcome to SharedMemory for cross-run learning.

        Stores the final result and key agent outputs as Facts so the
        context_retriever agent can find them in future executions.
        """
        if not self.shared_memory:
            return

        from app.models.schemas.shared_memory_schemas import FactCreate

        try:
            # Build a summary of what was executed and the outcome
            outcome = "successful" if success else "failed"
            input_summary = ""
            if input_data:
                transcript = input_data.get("transcript") or input_data.get("challenge_text") or ""
                input_summary = transcript[:500] if transcript else str(input_data)[:500]

            # Collect final agent outputs (last wave typically has the final report)
            agent_outputs = []
            for wave_key, wave_data in results.items():
                if not isinstance(wave_data, dict) or "retries" in wave_key:
                    continue
                for agent_name, agent_result in wave_data.items():
                    if not isinstance(agent_result, dict):
                        continue
                    if agent_result.get("success"):
                        output = agent_result.get("output")
                        if isinstance(output, dict):
                            # Extract the most meaningful output field (full content)
                            for key in ("final_report", "report", "result", "summary"):
                                if key in output and output[key]:
                                    agent_outputs.append((agent_name, key, str(output[key])))
                                    break

            # Fact 1: Execution summary (always persisted)
            summary_text = (
                f"Execution {self._execution_id} ({outcome}): "
                f"{duration_ms}ms, input: {input_summary[:200]}"
            )
            tags = [
                f"execution:{outcome}",
                f"challenge:{self._challenge_id}" if self._challenge_id else "challenge:none",
            ]
            await self.shared_memory.create_fact(FactCreate(
                text=summary_text,
                confidence=0.9 if success else 0.5,
                source_agent_id="hybrid_orchestrator",
                execution_id=self._execution_id,
                project_id=self._project_id,
                tags=tags,
            ))

            # Fact 2+: Successful agent outputs (for context retrieval)
            for agent_name, output_key, output_text in agent_outputs:
                await self.shared_memory.create_fact(FactCreate(
                    text=f"[{agent_name}] {output_text}",
                    confidence=0.85,
                    source_agent_id=agent_name,
                    execution_id=self._execution_id,
                    project_id=self._project_id,
                    tags=[f"agent:{agent_name}", f"output:{output_key}", f"execution:{outcome}"],
                ))

            logger.info(
                f"Persisted {1 + len(agent_outputs)} facts to shared memory "
                f"for execution {self._execution_id}"
            )
        except Exception as e:
            # Learning is non-critical — never fail the execution because of it
            logger.warning(f"Failed to persist execution learnings: {e}")

    async def _create_sandbox_executor(self) -> Optional[Any]:
        """
        Create sandbox executor for secure skill execution.

        Uses DynamicSandboxService (Docker-based) which allows:
        - pip install at runtime
        - apt-get install at runtime
        - Network access for downloading models
        - Full Python stdlib access

        This is required for self-improving capabilities like audio transcription.
        """
        try:
            from app.services.autonomous_executor_service import AutonomousExecutorService

            # Use the new autonomous executor which wraps DynamicSandboxService
            executor = AutonomousExecutorService(
                db=self.db,
                enable_auto_build=True,
                enable_caching=True,
            )

            # Check if Docker is available
            if executor._sandbox.is_available():
                logger.info("Created DynamicSandbox executor (Docker-based, unrestricted)")
                return executor
            else:
                logger.warning("Docker not available, falling back to restricted executor")
                return None

        except Exception as e:
            logger.warning(f"Failed to create DynamicSandbox executor: {e}")
            logger.info("Skill execution will use AST-based fallback (restricted)")
            return None

    async def get_execution_status(
        self,
        execution_id: str
    ) -> dict[str, Any]:
        """Get status of an execution (for async tracking). Uses lock to prevent concurrent session access."""
        async with self._db_lock:
            try:
                result = await self.db.execute(
                    select(Execution).where(Execution.id == execution_id)
                )
                execution = result.scalar_one_or_none()
                if execution:
                    return {
                        "execution_id": execution.id,
                        "status": execution.status,
                        "agents_executed": execution.agents_executed,
                        "waves_executed": execution.waves_executed,
                        "duration_ms": execution.duration_ms
                    }
            except Exception as e:
                logger.warning(f"Failed to get execution status: {e}")
                try:
                    await self.db.rollback()
                except Exception:
                    pass
            return {
                "execution_id": execution_id,
                "status": "unknown"
            }

    async def _emit_agent_event(
        self,
        event_type: str,
        agent_id: str,
        agent_name: str,
        wave: int,
        data: Optional[dict] = None,
        error: Optional[str] = None
    ) -> None:
        """
        Emit an agent execution event to the database.

        Events are consumed by SSE endpoint for real-time timeline updates.
        Uses a dedicated short-lived DB session to avoid conflicts with
        the main execution session (which may be mid-transaction).
        """
        try:
            from app.dependencies.dependencies import AsyncSessionLocal
            async with AsyncSessionLocal() as session:
                event = AgentExecutionEvent(
                    id=str(uuid4()),
                    execution_id=self._execution_id,
                    agent_id=agent_id,
                    agent_name=agent_name,
                    event_type=event_type,
                    wave=wave,
                    data=data,
                    error=error
                )
                session.add(event)
                await session.commit()
                logger.debug(f"Emitted {event_type} event for agent {agent_name}")
        except Exception as e:
            # Table may not exist if migration not run - log and continue
            logger.warning(f"Failed to emit agent event: {e}")

    async def _create_execution_record(
        self,
        input_data: Optional[dict] = None
    ) -> None:
        """Create execution record at start. Uses lock to prevent concurrent session access."""
        async with self._db_lock:
            try:
                execution = Execution(
                    id=self._execution_id,
                    challenge_id=self._challenge_id,
                    project_id=self._project_id,
                    status="running",
                    input_data=input_data
                )
                self.db.add(execution)
                await self.db.commit()
                logger.debug(f"Created execution record: {self._execution_id}")
            except Exception as e:
                # Table may not exist if migration not run - log and continue
                logger.warning(f"Failed to create execution record (table may not exist): {e}")
                try:
                    await self.db.rollback()
                except Exception:
                    pass

    async def _update_execution_record(
        self,
        status: str,
        results: Optional[dict] = None,
        waves_executed: int = 0,
        agents_executed: int = 0,
        duration_ms: Optional[int] = None,
        error: Optional[str] = None,
        completed_at: Optional[datetime] = None
    ) -> None:
        """Update execution record with progress or completion. Uses lock to prevent concurrent session access."""
        async with self._db_lock:
            try:
                result = await self.db.execute(
                    select(Execution).where(Execution.id == self._execution_id)
                )
                execution = result.scalar_one_or_none()
                if execution:
                    execution.status = status
                    if results is not None:
                        execution.results = results
                    if waves_executed:
                        execution.waves_executed = waves_executed
                    if agents_executed:
                        execution.agents_executed = agents_executed
                    if duration_ms is not None:
                        execution.duration_ms = duration_ms
                    if error:
                        execution.error = error
                    if completed_at:
                        execution.completed_at = completed_at
                    await self.db.commit()
                    logger.debug(f"Updated execution record: {self._execution_id} -> {status}")
            except Exception as e:
                # Table may not exist if migration not run - log and continue
                logger.warning(f"Failed to update execution record (table may not exist): {e}")
                try:
                    await self.db.rollback()
                except Exception:
                    pass


async def create_hybrid_orchestrator(
    db: AsyncSession,
    llm_client: Any
) -> HybridOrchestrator:
    """Factory function to create initialized orchestrator."""
    orchestrator = HybridOrchestrator(db=db, llm_client=llm_client)
    await orchestrator.initialize()
    return orchestrator


# --------------------------------------------------------------------------
# Sprint 1: Autonomous Evolution Loop helpers (fire-and-forget background task)
# --------------------------------------------------------------------------

async def _run_evolution_loop_safely(
    execution_id: str,
    agent_id: str = "unknown",
    input_data: Optional[dict] = None,
    tokens_input: int = 0,
    tokens_output: int = 0,
    outcome: str = "success",
    error_message: Optional[str] = None,
) -> None:
    """Run EvolutionLoopService with an isolated DB session.

    Erstellt zuerst die fehlende ExecutionTelemetry-Row (Bridge zwischen
    Execution-Tabelle und AnalysisPipeline), dann startet die Evolution-Loop.
    """
    from app.dependencies.dependencies import AsyncSessionLocal
    from app.dependencies.evolution_loop import build_evolution_loop_service
    from app.repositories.telemetry_repository import TelemetryRepository
    from app.services.telemetry_service import TelemetryService

    async with AsyncSessionLocal() as session:
        # Telemetrie-Row erstellen, damit AnalysisPipeline Findings generiert
        telemetry_repo = TelemetryRepository(session)
        telemetry_svc = TelemetryService(telemetry_repo)
        try:
            telemetry = await telemetry_svc.start_execution(
                agent_id=agent_id,
                execution_id=execution_id,
                input_data=input_data or {},
                metadata={"source": "hybrid_orchestrator"},
            )
            await telemetry_svc.complete_execution(
                telemetry_id=telemetry.id,
                output_data={},
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                outcome=outcome,
                error_message=error_message,
            )
            await session.commit()
        except Exception as e:
            logger.warning(f"Telemetrie-Bridge fehlgeschlagen: {e}")
            await session.rollback()

        # Evolution-Loop ausführen (findet jetzt die Telemetrie-Row)
        service = build_evolution_loop_service(session)
        await service.run_post_execution_evolution(execution_id)


def _log_evolution_task_exception(task: asyncio.Task, execution_id: str) -> None:
    """add_done_callback handler: explicit exception logging to prevent silent failures."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "Evolution task failed for %s: %s",
            execution_id,
            exc,
            exc_info=exc,
        )
