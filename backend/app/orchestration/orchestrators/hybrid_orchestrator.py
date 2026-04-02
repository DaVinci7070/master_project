"""Hybrid Orchestrator combining Shared Memory + Artifact Passing."""
import asyncio
import logging
from datetime import datetime, timezone
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

        # 7. Clear session artifacts
        await self._artifact_pool.clear()

        end_time = datetime.now(timezone.utc)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        result = {
            "success": True,
            "execution_id": self._execution_id,
            "results": results,
            "duration_ms": duration_ms,
            "waves_executed": len(waves),
            "agents_executed": sum(len(w) for w in waves)
        }

        # Update execution record with completion
        await self._update_execution_record(
            status="completed",
            results=results,
            waves_executed=len(waves),
            agents_executed=sum(len(w) for w in waves),
            duration_ms=duration_ms,
            completed_at=end_time
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

        for agent_id in agent_ids:
            agent = topology.get_agent(agent_id)
            if not agent:
                logger.warning(f"Agent {agent_id} not found in topology")
                continue

            # Emit agent_start event
            await self._emit_agent_event(
                event_type="agent_start",
                agent_id=agent_id,
                agent_name=agent.name,
                wave=wave_number
            )

            task = self._execute_agent_with_events(agent, input_data, wave_number)
            # Store agent name along with task for result mapping
            tasks.append((agent.name, agent_id, task))

        # Execute in parallel
        wave_results: dict[str, Any] = {}
        if tasks:
            agent_tasks = [t for _, _, t in tasks]
            results = await asyncio.gather(*agent_tasks, return_exceptions=True)

            for (agent_name, agent_id, _), result in zip(tasks, results):
                if isinstance(result, Exception):
                    wave_results[agent_name] = {
                        "success": False,
                        "error": str(result),
                        "agent_id": agent_id
                    }
                else:
                    # Add agent metadata to result
                    if isinstance(result, dict):
                        result["agent_id"] = agent_id
                        result["agent_name"] = agent_name
                    wave_results[agent_name] = result

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
