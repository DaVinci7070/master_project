import asyncio
import json
import logging
import time
import uuid
from typing import Optional

from opentelemetry import trace

from app.core.llm_client import LLMClient, LLMError
from app.models.schemas.developer_team_schemas import (
    AgentContext,
    AgentStatus,
    CodingAgentOutput,
    SpawnedAgent,
    SpawnRequest,
    SpawnResult,
    SubtaskSpec,
)
from app.prompts.coding_agent_prompt import (
    CODING_AGENT_SYSTEM_PROMPT,
    build_coding_agent_prompt,
)
from app.orchestration.agents.registry import RuntimeAgentRegistry

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class AgentSpawnerService:
    """
    Spawns and manages coding agents for multi-file tasks.

    Each spawn:
    1. Acquires a slot (respects max_concurrent limit)
    2. Registers agent in RuntimeAgentRegistry
    3. Calls LLM with scoped context
    4. Returns SpawnResult with generated code or error

    Example:
        registry = RuntimeAgentRegistry(max_concurrent_agents=5)
        llm_client = LLMClient()
        spawner = AgentSpawnerService(registry, llm_client)

        request = SpawnRequest(
            task_id=task.task_id,
            subtask=subtask,
            context=agent_context,
            timeout_seconds=300
        )

        result = await spawner.spawn_and_execute(request)
        if result.success:
            print(result.generated_code)
    """

    def __init__(
        self,
        registry: RuntimeAgentRegistry,
        llm_client: LLMClient,
        default_timeout: int = 300,
    ):
        """
        Initialize the spawner service.

        Args:
            registry: RuntimeAgentRegistry for tracking agents.
            llm_client: LLMClient for code generation.
            default_timeout: Default timeout in seconds (5 minutes).
        """
        self.registry = registry
        self.llm = llm_client
        self.default_timeout = default_timeout
        self.log = log

    async def spawn_and_execute(
        self,
        request: SpawnRequest,
    ) -> SpawnResult:
        """
        Spawn a coding agent and execute its task.

        This is the main entry point for spawning agents. It handles:
        - Slot acquisition (respects concurrency limits)
        - Agent registration and status tracking
        - LLM execution with timeout
        - Response parsing and validation
        - Cleanup on completion or failure

        Args:
            request: SpawnRequest with task and context details.

        Returns:
            SpawnResult with generated code or error details.
        """
        agent_id = str(uuid.uuid4())
        start_time = time.time()

        with tracer.start_as_current_span(
            "agent_spawner.spawn_and_execute",
            attributes={
                "agent.id": agent_id,
                "agent.task_id": request.task_id,
                "agent.file_path": request.subtask.file_path,
                "agent.timeout_seconds": request.timeout_seconds,
            }
        ) as span:
            try:
                slot_acquired = await self.registry.acquire_slot()
                if not slot_acquired:
                    self.log.warning(
                        f"Cannot spawn agent: no slots available for {request.subtask.file_path}"
                    )
                    return SpawnResult(
                        agent_id=agent_id,
                        success=False,
                        file_path=request.subtask.file_path,
                        error_message="No spawn slots available (max concurrent agents reached)",
                        duration_seconds=time.time() - start_time,
                    )

                agent = await self.registry.register(
                    agent_id=agent_id,
                    task_id=request.task_id,
                    file_path=request.subtask.file_path,
                )
                span.set_attribute("agent.registered", True)

                await self.registry.update_status(agent_id, AgentStatus.RUNNING)

                try:
                    result = await asyncio.wait_for(
                        self._execute_agent(request, agent_id),
                        timeout=request.timeout_seconds or self.default_timeout,
                    )
                    result_dict = result.model_dump() if hasattr(result, 'model_dump') else result

                    if result.success:
                        await self.registry.update_status(agent_id, AgentStatus.COMPLETED)
                    else:
                        await self.registry.update_status(
                            agent_id, AgentStatus.FAILED, error_message=result.error_message
                        )

                    span.set_attribute("agent.success", result.success)
                    span.set_attribute("agent.duration_seconds", result.duration_seconds)

                    return result

                except asyncio.TimeoutError:
                    self.log.warning(
                        f"Agent timed out: id={agent_id[:8]}..., "
                        f"timeout={request.timeout_seconds}s"
                    )
                    await self.registry.update_status(
                        agent_id, AgentStatus.FAILED, error_message="Execution timeout"
                    )
                    span.set_attribute("agent.timeout", True)

                    return SpawnResult(
                        agent_id=agent_id,
                        success=False,
                        file_path=request.subtask.file_path,
                        error_message=f"Execution timeout after {request.timeout_seconds}s",
                        duration_seconds=time.time() - start_time,
                    )

            except Exception as e:
                self.log.error(f"Spawn failed: {e}", exc_info=True)
                span.record_exception(e)

                try:
                    await self.registry.update_status(
                        agent_id, AgentStatus.FAILED, error_message=str(e)
                    )
                except Exception:
                    pass

                return SpawnResult(
                    agent_id=agent_id,
                    success=False,
                    file_path=request.subtask.file_path,
                    error_message=f"Spawn error: {str(e)}",
                    duration_seconds=time.time() - start_time,
                )

            finally:
                try:
                    await self.registry.release_slot()
                except Exception as e:
                    self.log.warning(f"Failed to release slot: {e}")

    async def _execute_agent(
        self,
        request: SpawnRequest,
        agent_id: str,
    ) -> SpawnResult:
        """
        Execute the agent's coding task via LLM.

        Uses Instructor for structured output to ensure valid responses.

        Args:
            request: SpawnRequest with context.
            agent_id: UUID of this agent.

        Returns:
            SpawnResult with code or error.
        """
        start_time = time.time()

        user_prompt = build_coding_agent_prompt(
            file_path=request.subtask.file_path,
            task_description=request.subtask.task_description,
            interface_contract=request.subtask.interface_contract,
            dependencies=request.subtask.required_files,
            additional_context=request.context.additional_context,
        )

        self.log.info(
            f"Executing agent id={agent_id[:8]}..., file={request.subtask.file_path}"
        )

        try:
            output: CodingAgentOutput = await self.llm.chat_structured(
                messages=[
                    {"role": "system", "content": CODING_AGENT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_model=CodingAgentOutput,
                temperature=0.3,
                max_retries=3,
            )

            duration = time.time() - start_time
            self.log.info(
                f"Agent completed id={agent_id[:8]}..., duration={duration:.2f}s"
            )

            return SpawnResult(
                agent_id=agent_id,
                success=True,
                file_path=request.subtask.file_path,
                generated_code=output.code,
                duration_seconds=duration,
                tokens_used=0,
                stdout=json.dumps({
                    "rationale": output.rationale,
                    "assumptions": output.assumptions,
                    "imports": output.imports,
                }),
            )

        except LLMError as e:
            self.log.warning(f"LLM error in agent {agent_id[:8]}...: {e}")
            return SpawnResult(
                agent_id=agent_id,
                success=False,
                file_path=request.subtask.file_path,
                error_message=f"LLM error: {str(e)}",
                duration_seconds=time.time() - start_time,
            )

        except Exception as e:
            self.log.error(f"Unexpected error in agent {agent_id[:8]}...: {e}")
            return SpawnResult(
                agent_id=agent_id,
                success=False,
                file_path=request.subtask.file_path,
                error_message=f"Execution error: {str(e)}",
                duration_seconds=time.time() - start_time,
            )

    async def cancel_agent(self, agent_id: str) -> bool:
        """
        Cancel a running agent.

        Args:
            agent_id: Agent to cancel.

        Returns:
            True if agent was cancelled, False if not found or already completed.
        """
        agent = await self.registry.get(agent_id)
        if not agent:
            return False

        if agent.status not in (AgentStatus.PENDING, AgentStatus.RUNNING):
            self.log.info(f"Agent {agent_id[:8]}... already in terminal state")
            return False

        await self.registry.update_status(agent_id, AgentStatus.CANCELLED)
        self.log.info(f"Cancelled agent {agent_id[:8]}...")
        return True

    async def cleanup_agent(self, agent_id: str) -> None:
        """
        Clean up agent resources after completion.

        Removes agent from registry. Called after result is processed.

        Args:
            agent_id: Agent to clean up.
        """
        await self.registry.unregister(agent_id)
        self.log.debug(f"Cleaned up agent {agent_id[:8]}...")
