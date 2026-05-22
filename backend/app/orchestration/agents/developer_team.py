"""
Developer Team Orchestrator for coordinating multi-file coding tasks.

This service implements the Orchestrator-Worker pattern:
1. Analyze task complexity via LLM
2. Decompose into file-level subtasks
3. Spawn coding agents in parallel waves using asyncio.TaskGroup
4. Synthesize results and handle partial failures
5. Clean up all agents after completion

Flow:
    DevelopmentTask -> decompose() -> [SubtaskSpec, ...]
    -> spawn agents per wave via TaskGroup
    -> collect SpawnResults -> TaskResult

Architecture follows RESEARCH.md patterns:
- asyncio.TaskGroup for structured concurrency
- Parallel Context Isolation (PCI) for agents
- OpenTelemetry for distributed tracing
- Automatic cleanup via try/finally
"""
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from opentelemetry import trace

from app.core.llm_client import LLMClient, LLMError
from app.models.schemas.developer_team_schemas import (
    AgentContext,
    AgentStatus,
    DevelopmentTask,
    SpawnRequest,
    SpawnResult,
    SubtaskSpec,
    TaskDecomposition,
    TaskDecompositionOutput,
)
from app.prompts.task_decomposition_prompt import (
    TASK_DECOMPOSITION_SYSTEM_PROMPT,
    build_decomposition_prompt,
)
from app.orchestration.agents.spawner import AgentSpawnerService
from app.orchestration.agents.registry import RuntimeAgentRegistry

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class TaskResult:
    """Result of executing a complex multi-file task."""
    task_id: str
    success: bool
    results: List[SpawnResult]
    files_completed: List[str]
    files_failed: List[str]
    total_duration_seconds: float
    total_tokens_used: int
    error_summary: Optional[str] = None


class DeveloperTeamOrchestrator:
    """
    Orchestrates complex multi-file development tasks.

    The orchestrator:
    1. Receives a DevelopmentTask with multiple files
    2. Uses LLM to decompose into subtasks with dependency graph
    3. Spawns coding agents in parallel waves
    4. Collects results and handles failures gracefully
    5. Returns aggregated TaskResult

    Example:
        registry = RuntimeAgentRegistry(max_concurrent_agents=5)
        llm_client = LLMClient()
        spawner = AgentSpawnerService(registry, llm_client)
        orchestrator = DeveloperTeamOrchestrator(spawner, llm_client, registry)

        task = DevelopmentTask(
            task_id=str(uuid.uuid4()),
            description="Create user management module",
            files_involved=["models/user.py", "api/users.py"],
            context_files=["models/base.py"],
        )

        result = await orchestrator.execute_complex_task(task)
        for spawn_result in result.results:
            if spawn_result.success:
                print(f"Generated: {spawn_result.file_path}")
    """

    def __init__(
        self,
        spawner: AgentSpawnerService,
        llm_client: LLMClient,
        registry: RuntimeAgentRegistry,
        max_parallel_per_wave: int = 5,
    ):
        """
        Initialize the orchestrator.

        Args:
            spawner: AgentSpawnerService for spawning coding agents.
            llm_client: LLMClient for task decomposition.
            registry: RuntimeAgentRegistry for tracking agents.
            max_parallel_per_wave: Max agents to spawn in parallel per wave.
        """
        self.spawner = spawner
        self.llm = llm_client
        self.registry = registry
        self.max_parallel = max_parallel_per_wave
        self.log = log

    async def execute_complex_task(
        self,
        task: DevelopmentTask,
    ) -> TaskResult:
        """
        Execute a complex multi-file development task.

        This is the main entry point. It:
        1. Decomposes task into subtasks
        2. Executes subtasks in parallel waves
        3. Handles failures gracefully (continues with successful agents)
        4. Returns aggregated results

        Args:
            task: DevelopmentTask to execute.

        Returns:
            TaskResult with all spawn results.
        """
        start_time = time.time()

        with tracer.start_as_current_span(
            "developer_team.execute_complex_task",
            attributes={
                "task.id": task.task_id,
                "task.files_count": len(task.files_involved),
            }
        ) as span:
            try:
                # 1. Decompose task into subtasks
                self.log.info(
                    f"Decomposing task id={task.task_id[:8]}..., "
                    f"files={len(task.files_involved)}"
                )
                decomposition = await self._decompose_task(task)
                span.set_attribute("task.subtasks_count", len(decomposition.subtasks))
                span.set_attribute("task.waves_count", len(decomposition.execution_order))

                # 2. Execute subtasks in waves
                all_results: List[SpawnResult] = []
                completed_files: Dict[str, str] = {}  # file_path -> generated_code

                for wave_idx, wave_files in enumerate(decomposition.execution_order):
                    self.log.info(
                        f"Executing wave {wave_idx + 1}/{len(decomposition.execution_order)}, "
                        f"files={wave_files}"
                    )

                    wave_results = await self._execute_wave(
                        task=task,
                        decomposition=decomposition,
                        wave_files=wave_files,
                        completed_files=completed_files,
                    )

                    all_results.extend(wave_results)

                    # Update completed files for next wave's context
                    for result in wave_results:
                        if result.success and result.generated_code:
                            completed_files[result.file_path] = result.generated_code

                # 3. Aggregate results
                files_completed = [r.file_path for r in all_results if r.success]
                files_failed = [r.file_path for r in all_results if not r.success]
                total_tokens = sum(r.tokens_used for r in all_results)

                error_summary = None
                if files_failed:
                    errors = [f"{r.file_path}: {r.error_message}" for r in all_results if not r.success]
                    error_summary = "; ".join(errors)

                span.set_attribute("task.files_completed", len(files_completed))
                span.set_attribute("task.files_failed", len(files_failed))
                span.set_attribute("task.success", len(files_failed) == 0)

                return TaskResult(
                    task_id=task.task_id,
                    success=len(files_failed) == 0,
                    results=all_results,
                    files_completed=files_completed,
                    files_failed=files_failed,
                    total_duration_seconds=time.time() - start_time,
                    total_tokens_used=total_tokens,
                    error_summary=error_summary,
                )

            except Exception as e:
                self.log.error(f"Task execution failed: {e}", exc_info=True)
                span.record_exception(e)

                return TaskResult(
                    task_id=task.task_id,
                    success=False,
                    results=[],
                    files_completed=[],
                    files_failed=task.files_involved,
                    total_duration_seconds=time.time() - start_time,
                    total_tokens_used=0,
                    error_summary=str(e),
                )

            finally:
                # Clean up all agents for this task
                await self._cleanup_task_agents(task.task_id)

    async def _decompose_task(
        self,
        task: DevelopmentTask,
    ) -> TaskDecomposition:
        """
        Decompose a task into subtasks using LLM with structured output.

        Uses Instructor to guarantee valid, parseable responses.

        Args:
            task: DevelopmentTask to decompose.

        Returns:
            TaskDecomposition with subtasks and execution order.

        Raises:
            LLMError: If LLM call fails after retries.
        """
        with tracer.start_as_current_span("developer_team.decompose_task"):
            user_prompt = build_decomposition_prompt(
                description=task.description,
                files_involved=task.files_involved,
                context_files=task.context_files,
                constraints=task.constraints,
            )

            # Use Instructor for structured output - guarantees valid response
            output: TaskDecompositionOutput = await self.llm.chat_structured(
                messages=[
                    {"role": "system", "content": TASK_DECOMPOSITION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_model=TaskDecompositionOutput,
                temperature=0.2,  # Deterministic decomposition
                max_retries=3,  # Instructor will retry on validation failures
            )

            # Convert to TaskDecomposition (adds task_id)
            decomposition = TaskDecomposition(
                task_id=task.task_id,
                subtasks=output.subtasks,
                execution_order=output.execution_waves,
                shared_context=output.shared_context,
                rationale=output.rationale,
            )

            self.log.info(
                f"Decomposed task into {len(decomposition.subtasks)} subtasks, "
                f"{len(decomposition.execution_order)} waves"
            )

            return decomposition

    async def _execute_wave(
        self,
        task: DevelopmentTask,
        decomposition: TaskDecomposition,
        wave_files: List[str],
        completed_files: Dict[str, str],
    ) -> List[SpawnResult]:
        """
        Execute a single wave of subtasks in parallel.

        Uses asyncio.TaskGroup for structured concurrency:
        - All tasks in wave run in parallel
        - If one fails, others continue (no cancellation)
        - Wait for all to complete before returning

        Args:
            task: Original DevelopmentTask.
            decomposition: Task decomposition with subtasks.
            wave_files: File paths to execute in this wave.
            completed_files: Already completed files (for context).

        Returns:
            List of SpawnResults from this wave.
        """
        # Find subtasks for this wave
        subtasks = [
            s for s in decomposition.subtasks
            if s.file_path in wave_files
        ]

        if not subtasks:
            return []

        results: List[SpawnResult] = []
        spawn_tasks: List[asyncio.Task] = []

        with tracer.start_as_current_span(
            "developer_team.execute_wave",
            attributes={"wave.files": wave_files}
        ):
            # Use TaskGroup for structured concurrency
            try:
                async with asyncio.TaskGroup() as tg:
                    for subtask in subtasks[:self.max_parallel]:
                        # Build context with completed files
                        additional_context = self._build_context_from_completed(
                            subtask, completed_files, decomposition.shared_context
                        )

                        context = AgentContext(
                            file_path=subtask.file_path,
                            dependencies=subtask.required_files,
                            interface_contract=subtask.interface_contract,
                            parent_task_id=task.task_id,
                            additional_context=additional_context,
                        )

                        request = SpawnRequest(
                            task_id=task.task_id,
                            subtask=subtask,
                            context=context,
                            timeout_seconds=300,  # 5 minutes per file
                        )

                        # Create task
                        t = tg.create_task(
                            self.spawner.spawn_and_execute(request),
                            name=f"spawn-{subtask.file_path}",
                        )
                        spawn_tasks.append(t)

                # Collect results (TaskGroup waits for all)
                results = [t.result() for t in spawn_tasks]

            except* Exception as eg:
                # ExceptionGroup from TaskGroup - some tasks failed
                self.log.warning(f"Some wave tasks failed: {eg.exceptions}")
                # Collect whatever results we have
                for t in spawn_tasks:
                    if t.done() and not t.cancelled():
                        try:
                            results.append(t.result())
                        except Exception:
                            pass

        return results

    def _build_context_from_completed(
        self,
        subtask: SubtaskSpec,
        completed_files: Dict[str, str],
        shared_context: Dict[str, Any],
    ) -> str:
        """
        Build additional context string from completed files.

        Args:
            subtask: Current subtask.
            completed_files: Map of file_path -> generated_code.
            shared_context: Shared context from decomposition.

        Returns:
            Context string for the agent.
        """
        lines = []

        # Add relevant completed files
        for dep in subtask.required_files:
            if dep in completed_files:
                lines.append(f"## Completed: {dep}")
                lines.append("```python")
                # Truncate if very long
                code = completed_files[dep]
                if len(code) > 2000:
                    code = code[:2000] + "\n# ... truncated ..."
                lines.append(code)
                lines.append("```")
                lines.append("")

        # Add shared context
        if shared_context:
            lines.append("## Shared Context")
            lines.append(json.dumps(shared_context, indent=2))

        return "\n".join(lines) if lines else ""

    async def _cleanup_task_agents(self, task_id: str) -> None:
        """
        Clean up all agents belonging to a task.

        Called in finally block to ensure cleanup.

        Args:
            task_id: Task UUID to clean up.
        """
        agents = await self.registry.get_by_task(task_id)
        for agent in agents:
            try:
                await self.spawner.cleanup_agent(agent.agent_id)
            except Exception as e:
                self.log.warning(f"Cleanup failed for agent {agent.agent_id[:8]}...: {e}")

        self.log.info(f"Cleaned up {len(agents)} agents for task {task_id[:8]}...")

    async def should_spawn_agents(
        self,
        files_count: int,
        task_complexity: str = "moderate",
    ) -> bool:
        """
        Heuristic to determine if task warrants agent spawning.

        Per RESEARCH.md pitfall #6: avoid spawning for trivial tasks.

        Args:
            files_count: Number of files involved.
            task_complexity: Estimated complexity.

        Returns:
            True if spawning is recommended.
        """
        # Per RESEARCH.md: spawn if >3 files or complex
        if files_count > 3:
            return True
        if task_complexity == "complex":
            return True
        if files_count > 1 and task_complexity == "moderate":
            return True
        return False
