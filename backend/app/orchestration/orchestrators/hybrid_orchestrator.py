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
        session_factory: Optional[SessionFactory] = None
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
        """
        self.db = db
        self.llm_client = llm_client
        self.topology_loader = topology_loader
        self.shared_memory = shared_memory
        self.context_manager = context_manager or ContextBudgetManager()
        self._session_factory = session_factory
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
            self.topology_loader = TopologyLoader(self.db)
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
                    context_manager=self.context_manager
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
        self._executor = GenericAgentExecutor(
            llm_client=self.llm_client,
            artifact_pool=self._artifact_pool,
            shared_memory=self.shared_memory,
            context_manager=self.context_manager,
            topology_loader=self.topology_loader,  # Pass for skill injection
            db=self.db,  # Pass for auto-creating skills
            sandbox_executor=sandbox_executor  # Pass for secure skill execution
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

        result = {
            "success": overall_success,
            "execution_id": self._execution_id,
            "results": results,
            "duration_ms": duration_ms,
            "waves_executed": len(waves),
            "agents_executed": sum(len(w) for w in waves),
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

        for agent_id in agent_ids:
            agent = topology.get_agent(agent_id)
            if not agent:
                logger.warning(f"Agent {agent_id} not found in topology")
                continue

            # Check if dependencies are satisfied before dispatching
            skip_reason = self._should_skip_agent(agent)
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

            # Emit agent_start event
            await self._emit_agent_event(
                event_type="agent_start",
                agent_id=agent_id,
                agent_name=agent.name,
                wave=wave_number
            )

            task = self._execute_agent_with_events(agent, input_data, wave_number)
            tasks.append((agent.name, agent_id, task))

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
                else:
                    if isinstance(result, dict):
                        result["agent_id"] = agent_id
                        result["agent_name"] = agent_name
                    wave_results[agent_name] = result
                    result_dict = result if isinstance(result, dict) else {}

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
        wave_number: int
    ) -> dict[str, Any]:
        """Execute agent and emit completion/error events."""
        try:
            result = await self._execute_agent(agent, input_data)

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

    async def _execute_agent(
        self,
        agent: AgentNode,
        input_data: Optional[dict]
    ) -> dict[str, Any]:
        """Execute a single agent."""
        # Get prompt from database
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

    def _should_skip_agent(self, agent: AgentNode) -> Optional[str]:
        """Check if agent should be skipped due to failed dependencies."""
        for consumed_type in agent.consumes_artifacts:
            for record in self._failure_tracker.values():
                if consumed_type in record.produces_artifacts and not record.resolved:
                    return (
                        f"Artifact '{consumed_type}' unavailable: "
                        f"agent '{record.agent_name}' failed"
                    )
        return None

    def _get_prompt_improver(self) -> Any:
        """Lazy-init AgentPromptImprover for retry repairs."""
        if not self._prompt_improver:
            from app.services.agent_prompt_improver import AgentPromptImprover

            async def llm_wrapper(messages: list[dict]) -> str:
                response = await self.llm_client.chat(messages)
                return response.content

            self._prompt_improver = AgentPromptImprover(self.db, llm_fn=llm_wrapper)
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
            self._capability_builder = CapabilityBuilder(developer_team, self.db)
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
                result = await self._execute_agent_with_events(agent_node, input_data, wave_number)

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
        Uses lock to prevent concurrent session access.
        """
        async with self._db_lock:
            try:
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
                self.db.add(event)
                await self.db.commit()
                logger.debug(f"Emitted {event_type} event for agent {agent_name}")
            except Exception as e:
                # Table may not exist if migration not run - log and continue
                logger.warning(f"Failed to emit agent event (table may not exist): {e}")
                try:
                    await self.db.rollback()
                except Exception:
                    pass

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
