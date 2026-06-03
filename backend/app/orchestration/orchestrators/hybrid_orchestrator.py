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
from app.orchestration.artifacts.models import Artifact
from app.orchestration.shared_memory.service import SharedMemoryService
from app.orchestration.executors.generic_executor import GenericAgentExecutor
from app.orchestration.context_manager import ContextBudgetManager
from app.orchestration.verification.execution_verifier import ExecutionVerifier
from app.orchestration.verification.adapt_strategy import AdaptStrategy
from app.models.schemas.team_schemas import AdaptAction, TeamPlan, GapReport, VerificationResult
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
        execution_verifier: Optional[ExecutionVerifier] = None,
        adapt_strategy: Optional[AdaptStrategy] = None,
        team_assembler: Optional[Any] = None,
        agent_promotion: Optional[Any] = None,
        strategy_memory: Optional[Any] = None,
    ):
        self.db = db
        self.llm_client = llm_client
        self.topology_loader = topology_loader
        self.shared_memory = shared_memory
        self.context_manager = context_manager or ContextBudgetManager()
        self._session_factory = session_factory
        self._embedding_fn = embedding_fn
        self._db_lock = asyncio.Lock()

        self._execution_verifier = execution_verifier
        self._adapt_strategy = adapt_strategy

        self._team_assembler = team_assembler
        self._agent_promotion = agent_promotion
        self._strategy_memory = strategy_memory

        self._artifact_pool: Optional[ArtifactPool] = None
        self._executor: Optional[GenericAgentExecutor] = None
        self._execution_id: Optional[str] = None
        self._current_wave: int = 0
        self._project_id: str = "default"
        self._challenge_id: Optional[str] = None

        self._failure_tracker: dict[str, AgentFailureRecord] = {}
        self._max_retries_per_agent = 2
        self._prompt_improver: Optional[Any] = None
        self._capability_builder: Optional[Any] = None

    async def initialize(self) -> None:
        """Initialize orchestrator components."""
        if not self.topology_loader:
            self.topology_loader = TopologyLoader(self._session_factory)
            await self.topology_loader.load()

        if not self.shared_memory:
            try:
                from app.orchestration.shared_memory.qdrant_adapter import SharedMemoryQdrantAdapter
                from qdrant_client import QdrantClient

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

        phase_tokens = {
            "assembly": 0,
            "execution": 0,
            "verification": 0,
            "adapt": 0,
            "self_healing": 0,
        }

        logger.info(f"Starting execution: {self._execution_id}")

        from app.core.config import settings

        await self._create_execution_record(input_data)

        team_plan = None
        if self._team_assembler and settings.team_assembly_enabled and input_data:
            try:
                all_agents = await self._load_all_agents()
                all_skills = await self._load_all_skills()

                result = await self._team_assembler.assemble_team(
                    challenge_text=input_data.get("challenge", ""),
                    available_agents=all_agents,
                    available_skills=all_skills,
                )
                phase_tokens["assembly"] += self._team_assembler._last_tokens_used

                if isinstance(result, GapReport):
                    logger.info(
                        f"TeamAssembler meldet Gaps: {len(result.missing_capabilities)} fehlende Capabilities"
                    )
                    await self._handle_team_gaps(result)
                    all_agents = await self._load_all_agents()
                    all_skills = await self._load_all_skills()
                    result = await self._team_assembler.assemble_team(
                        challenge_text=input_data.get("challenge", ""),
                        available_agents=all_agents,
                        available_skills=all_skills,
                    )
                    phase_tokens["assembly"] += self._team_assembler._last_tokens_used

                if isinstance(result, TeamPlan):
                    team_plan = result
                    logger.info(
                        f"Team assembled: {len(team_plan.agents)} agents, "
                        f"strategy='{team_plan.strategy}', "
                        f"{len(team_plan.execution_waves)} waves"
                    )
                else:
                    logger.warning("Team assembly: Gaps nach Gap-Build noch offen, Fallback")

            except Exception as e:
                logger.warning(f"Team assembly fehlgeschlagen, Fallback auf Default: {e}")
                team_plan = None

        if team_plan:
            topology, validation = await self.topology_loader.load_for_team(team_plan)
        else:
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

        self._artifact_pool = ArtifactPool(execution_id=self._execution_id)

        sandbox_executor = await self._create_sandbox_executor()

        intervention = None
        if settings.intra_execution_self_healing_enabled and self.db:
            try:
                from app.orchestration.intervention.orchestrator import create_intervention_orchestrator
                intervention = await create_intervention_orchestrator(
                    session_factory=self._session_factory,
                )
            except Exception as e:
                logger.warning(f"Could not create intervention orchestrator for self-healing: {e}")

        self._executor = GenericAgentExecutor(
            llm_client=self.llm_client,
            artifact_pool=self._artifact_pool,
            shared_memory=self.shared_memory,
            context_manager=self.context_manager,
            topology_loader=self.topology_loader,
            db=self.db,
            sandbox_executor=sandbox_executor,
            intervention_orchestrator=intervention,
        )

        self._original_input = input_data

        results: dict[str, Any] = {}
        waves = validation.execution_waves or [[]]

        for wave_idx, wave_agents in enumerate(waves):
            logger.info(f"Executing wave {wave_idx + 1}/{len(waves)}: {wave_agents}")

            wave_results = await self._execute_wave(
                agent_ids=wave_agents,
                topology=topology,
                input_data=input_data,
                wave_number=wave_idx + 1
            )

            results[f"wave_{wave_idx + 1}"] = wave_results

            for _ar in wave_results.values():
                if isinstance(_ar, dict):
                    phase_tokens["execution"] += _ar.get("tokens_total", 0) or 0

            topology, retry_results = await self._repair_and_retry(
                topology, input_data, wave_number=wave_idx + 1,
            )
            if retry_results:
                results[f"wave_{wave_idx + 1}_retries"] = retry_results
                for name, r in retry_results.items():
                    if isinstance(r, dict) and r.get("success"):
                        wave_results[name] = r

        adapt_rounds = 0
        last_verification = None

        if self._execution_verifier and settings.verify_adapt_enabled:
            final_output = self._extract_final_output(results)
            challenge_text = (input_data or {}).get("challenge", "")
            score_history: list[float] = []

            if final_output and challenge_text:
                for adapt_round in range(settings.max_adapt_rounds):
                    verification = await self._execution_verifier.verify(
                        final_output=final_output,
                        challenge_text=challenge_text,
                    )
                    phase_tokens["verification"] += self._execution_verifier._last_tokens_used
                    last_verification = verification

                    if verification.score_corrected:
                        await self._emit_agent_event(
                            event_type="reflexion",
                            agent_id="execution_verifier",
                            agent_name="ExecutionVerifier",
                            wave=adapt_round,
                            data={
                                "phase": "self_reflection",
                                "score_before": verification.original_score,
                                "score_after": verification.score,
                                "tokens_used": self._execution_verifier._reflection_token_count,
                            },
                        )

                    if verification.is_complete or verification.score >= settings.verification_completeness_threshold:
                        logger.info(f"Verification passed (score={verification.score:.2f})")
                        break

                    score_history.append(verification.score)
                    if len(score_history) >= 2 and (score_history[-1] - score_history[-2]) < 0.05:
                        logger.info(
                            f"Score-Stagnation: {score_history[-2]:.2f} -> {score_history[-1]:.2f}, "
                            f"Adapt-Loop beendet nach {adapt_round + 1} Runden"
                        )
                        break

                    decision = self._adapt_strategy.determine_action(verification, adapt_round)
                    adapt_rounds = adapt_round + 1

                    logger.info(
                        f"Verification: score={verification.score:.2f}, "
                        f"action={decision.action.value}, round {adapt_round + 1}"
                    )

                    if decision.action == AdaptAction.REPLAN_FEEDBACK:
                        await self._artifact_pool.write(Artifact(
                            artifact_type="verification_feedback",
                            payload=decision.feedback_artifact["payload"],
                            source_agent_id="execution_verifier",
                        ))

                        replan_agents = self._get_replan_agents(waves)
                        replan_results = await self._execute_wave(
                            agent_ids=replan_agents,
                            topology=topology,
                            input_data=input_data,
                            wave_number=100 + adapt_round,
                        )
                        results[f"adapt_feedback_{adapt_round + 1}"] = replan_results
                        for _ar in replan_results.values():
                            if isinstance(_ar, dict):
                                phase_tokens["adapt"] += _ar.get("tokens_total", 0) or 0
                        final_output = self._extract_final_output(results)

                    elif decision.action == AdaptAction.REPLAN_NEW_TEAM:
                        if not self._team_assembler:
                            logger.warning("REPLAN_NEW_TEAM braucht TeamAssembler, Fallback auf Feedback")
                            continue

                        await self._artifact_pool.clear()

                        all_agents = await self._load_all_agents()
                        all_skills = await self._load_all_skills()
                        new_plan = await self._team_assembler.replan_with_feedback(
                            challenge_text=challenge_text,
                            previous_plan=team_plan or TeamPlan(challenge_text=challenge_text, agents=[], rationale="default"),
                            verification=verification,
                            available_agents=all_agents,
                            available_skills=all_skills,
                        )
                        phase_tokens["adapt"] += self._team_assembler._last_tokens_used

                        if isinstance(new_plan, GapReport):
                            await self._handle_team_gaps(new_plan)
                            continue

                        team_plan = new_plan
                        topology, validation = await self.topology_loader.load_for_team(team_plan)
                        replan_waves = validation.execution_waves or [[]]

                        for w_idx, w_agents in enumerate(replan_waves):
                            w_results = await self._execute_wave(
                                agent_ids=w_agents,
                                topology=topology,
                                input_data=input_data,
                                wave_number=200 + adapt_round * 10 + w_idx,
                            )
                            results[f"adapt_newteam_{adapt_round + 1}_wave_{w_idx + 1}"] = w_results
                            for _ar in w_results.values():
                                if isinstance(_ar, dict):
                                    phase_tokens["adapt"] += _ar.get("tokens_total", 0) or 0

                        final_output = self._extract_final_output(results)

                    elif decision.action == AdaptAction.ESCALATE:
                        logger.info(f"Eskalation: Gap-Building für {decision.gaps_to_build}")
                        await self._escalate_to_gap_building(
                            gaps=decision.gaps_to_build or [],
                            challenge_text=challenge_text,
                            previous_output=final_output[:500] if final_output else "",
                            previous_score=verification.score,
                        )

                        await self._artifact_pool.clear()

                        if self._team_assembler:
                            all_agents = await self._load_all_agents()
                            all_skills = await self._load_all_skills()
                            new_plan = await self._team_assembler.assemble_team(
                                challenge_text=challenge_text,
                                available_agents=all_agents,
                                available_skills=all_skills,
                            )
                            phase_tokens["adapt"] += self._team_assembler._last_tokens_used

                            if isinstance(new_plan, TeamPlan):
                                team_plan = new_plan
                                topology, validation = await self.topology_loader.load_for_team(team_plan)
                                esc_waves = validation.execution_waves or [[]]

                                for w_idx, w_agents in enumerate(esc_waves):
                                    w_results = await self._execute_wave(
                                        agent_ids=w_agents,
                                        topology=topology,
                                        input_data=input_data,
                                        wave_number=300 + adapt_round * 10 + w_idx,
                                    )
                                    results[f"adapt_escalate_{adapt_round + 1}_wave_{w_idx + 1}"] = w_results

                                final_output = self._extract_final_output(results)
                            else:
                                topology, validation = await self.topology_loader.reload()
                                for wave_idx, wave_agents in enumerate(waves):
                                    wave_results = await self._execute_wave(
                                        agent_ids=wave_agents,
                                        topology=topology,
                                        input_data=input_data,
                                        wave_number=300 + adapt_round * 10 + wave_idx,
                                    )
                                    results[f"adapt_escalate_{adapt_round + 1}_wave_{wave_idx + 1}"] = wave_results

                                final_output = self._extract_final_output(results)
                        else:
                            topology, validation = await self.topology_loader.reload()
                            for wave_idx, wave_agents in enumerate(waves):
                                wave_results = await self._execute_wave(
                                    agent_ids=wave_agents,
                                    topology=topology,
                                    input_data=input_data,
                                    wave_number=300 + adapt_round * 10 + wave_idx,
                                )
                                results[f"adapt_escalate_{adapt_round + 1}_wave_{wave_idx + 1}"] = wave_results

                            final_output = self._extract_final_output(results)

        last_score = last_verification.score if last_verification else 0.0

        if self._strategy_memory and team_plan:
            try:
                strategy_tokens = sum(
                    r.get("tokens_total", 0) for w in results.values()
                    if isinstance(w, dict) for r in w.values() if isinstance(r, dict)
                )
                await self._strategy_memory.record_outcome(
                    team_plan=team_plan,
                    verification_score=last_score,
                    duration_ms=int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000),
                    tokens_total=strategy_tokens,
                    adapt_rounds=adapt_rounds,
                    execution_id=self._execution_id or "unknown",
                    project_id=self._project_id,
                    verification_feedback=last_verification.feedback_for_retry if last_verification else "",
                )
            except Exception as e:
                logger.warning(f"Strategy-Memory fehlgeschlagen: {e}")

        if self._agent_promotion and team_plan and last_score >= settings.agent_promotion_min_score:
            try:
                promoted = await self._agent_promotion.evaluate_and_promote(
                    execution_results=results,
                    verification_score=last_score,
                    team_plan=team_plan,
                )
                if promoted:
                    logger.info(f"Agents befördert: {promoted}")
            except Exception as e:
                logger.warning(f"Agent-Promotion fehlgeschlagen: {e}")

        await self._artifact_pool.clear()

        end_time = datetime.now(timezone.utc)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        unresolved = [f for f in self._failure_tracker.values() if not f.resolved]
        overall_success = len(unresolved) == 0
        if last_verification and last_verification.score >= settings.verification_completeness_threshold:
            overall_success = True

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

        reflexion_metrics = self._collect_reflexion_metrics(last_verification)

        phase_tokens_total = sum(phase_tokens.values())

        await self._write_orchestration_telemetry(
            phase_tokens=phase_tokens,
            phase_tokens_total=phase_tokens_total,
            adapt_rounds=adapt_rounds,
            verification_score=last_verification.score if last_verification else 0.0,
            created_at=start_time,
        )

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
            "tokens_assembly": phase_tokens["assembly"],
            "tokens_execution": phase_tokens["execution"],
            "tokens_verification": phase_tokens["verification"],
            "tokens_adapt": phase_tokens["adapt"],
            "tokens_self_healing": phase_tokens["self_healing"],
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
            "reflexion_metrics": reflexion_metrics,
        }

        await self._update_execution_record(
            status="completed" if overall_success else "failed",
            results=results,
            error="; ".join(f.error_message for f in unresolved)[:500] if unresolved else None,
            waves_executed=len(waves),
            agents_executed=sum(len(w) for w in waves),
            duration_ms=duration_ms,
            completed_at=end_time,
        )

        await self._persist_execution_learnings(
            results=results,
            success=overall_success,
            duration_ms=duration_ms,
            input_data=input_data,
        )

        _primary_agent_id = waves[0][0] if waves and waves[0] else "unknown"
        failed_tool_calls = self._collect_failed_tool_calls(results)
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
                        failed_tool_calls=failed_tool_calls,
                    )
                )
                task.add_done_callback(
                    lambda t, eid=self._execution_id: _log_evolution_task_exception(t, eid)
                )
        except Exception as e:
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

        _DEV_NAMES = {"product_owner", "control_agent", "prompt_engineer",
                      "tool_builder", "quality_judge", "execution_analyzer"}

        agents_to_run: list[AgentNode] = []
        for agent_id in agent_ids:
            agent = topology.get_agent(agent_id)
            if not agent:
                logger.warning(f"Agent {agent_id} not found in topology")
                continue
            if agent.name in _DEV_NAMES:
                logger.info(f"Skipping dev-team agent '{agent.name}' in execution wave")
                continue

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

        prompt_cache = await self._prefetch_prompts(agents_to_run)

        for agent in agents_to_run:
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

        if tasks:
            from app.core.config import settings as _settings
            _agent_timeout = float(_settings.agent_execution_timeout)

            async def _agent_with_timeout(coro, name, timeout):
                try:
                    return await asyncio.wait_for(coro, timeout=timeout)
                except asyncio.TimeoutError:
                    logger.warning(f"Agent '{name}' timed out after {timeout}s")
                    return {
                        "success": False,
                        "error": f"Agent timeout ({timeout}s)",
                        "failure_type": "timeout",
                    }

            agent_tasks = [
                _agent_with_timeout(t, name, _agent_timeout)
                for name, _, t in tasks
            ]
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

                is_failure = (
                    isinstance(result, Exception)
                    or (isinstance(result, dict) and not result.get("success", True))
                )
                if is_failure:
                    agent_node = topology.get_agent(agent_id)
                    error_msg = self._extract_tool_failure_context(result_dict)
                    self._failure_tracker[agent_id] = AgentFailureRecord(
                        agent_id=agent_id, agent_name=agent_name, wave=wave_number,
                        failure_type=self._classify_failure(result_dict),
                        error_message=error_msg,
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

    @staticmethod
    def _collect_failed_tool_calls(results: dict) -> list[dict]:
        """Sammelt fehlgeschlagene Tool-Calls aus allen Waves für den Evolution-Loop."""
        failed = []
        for wave_key, wave_results in results.items():
            if not isinstance(wave_results, dict):
                continue
            for agent_name, agent_result in wave_results.items():
                if not isinstance(agent_result, dict):
                    continue
                for tc in agent_result.get("tool_calls", []):
                    if isinstance(tc, dict) and not tc.get("result", {}).get("success", True):
                        failed.append({
                            "agent": agent_name,
                            "tool": tc.get("tool", "unknown"),
                            "arguments": tc.get("arguments", {}),
                            "error": str(tc.get("result", {}).get("error", ""))[:300],
                        })
        return failed

    @staticmethod
    def _extract_tool_failure_context(result: dict) -> str:
        """Extrahiert fehlgeschlagene Tool-Details für Self-Healing-Kontext."""
        tool_calls = result.get("tool_calls", [])
        failed = [
            t for t in tool_calls
            if isinstance(t, dict) and not t.get("result", {}).get("success", True)
        ]
        if failed:
            parts = []
            for t in failed:
                name = t.get("tool", "unknown")
                err = t.get("result", {}).get("output", "")
                if isinstance(err, str) and len(err) > 200:
                    err = err[:200]
                parts.append(f"Skill '{name}' fehlgeschlagen: {err}")
            return "; ".join(parts)
        return str(result.get("error", result.get("result", "Unknown error")))

    async def _should_skip_agent(self, agent: AgentNode, wave_number: int = 1) -> Optional[str]:
        """Check if agent should be skipped due to failed dependencies or missing artifacts."""
        for consumed_type in agent.consumes_artifacts:
            for record in self._failure_tracker.values():
                if consumed_type in record.produces_artifacts and not record.resolved:
                    return (
                        f"Artifact '{consumed_type}' unavailable: "
                        f"agent '{record.agent_name}' failed"
                    )
            if wave_number > 1:
                artifacts = await self._artifact_pool.read([consumed_type])
                if not artifacts:
                    return f"Artifact '{consumed_type}' not found in pool"
        return None

    def _get_prompt_improver(self) -> Any:
        """Lazy-init AgentPromptImprover for retry repairs."""
        if not self._prompt_improver:
            from app.feedback_loop.improvement.prompt_improver import AgentPromptImprover

            async def llm_wrapper(messages: list[dict]) -> str:
                response = await self.llm_client.chat(messages)
                return response.content

            self._prompt_improver = AgentPromptImprover(self._session_factory, llm_fn=llm_wrapper)
        return self._prompt_improver

    def _get_capability_builder(self) -> Any:
        """Lazy-init CapabilityBuilder for skill repair."""
        if not self._capability_builder:
            from app.orchestration.intervention.builder import CapabilityBuilder
            from app.orchestration.agents.developer_team import DeveloperTeamOrchestrator
            from app.orchestration.agents.spawner import AgentSpawnerService
            from app.orchestration.agents.registry import RuntimeAgentRegistry

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
    ) -> tuple[Topology, dict[str, Any]]:
        """Attempt to repair and retry failed agents from a wave.

        Returns (topology, retry_results) — Topologie kann sich durch Skill-Build aendern.
        """
        retryable = {
            aid: rec for aid, rec in self._failure_tracker.items()
            if rec.wave == wave_number
            and not rec.resolved
            and rec.failure_type != FailureType.BAD_INPUT
            and rec.retries_attempted < self._max_retries_per_agent
            and not (rec.failure_type == FailureType.UNKNOWN and rec.retries_attempted >= 1)
        }

        if not retryable:
            return topology, {}

        logger.info(
            f"Wave {wave_number} self-healing: {len(retryable)} agents to retry: "
            f"{[r.agent_name for r in retryable.values()]}"
        )

        retry_results: dict[str, Any] = {}

        retry_agents = [topology.get_agent(aid) for aid in retryable if topology.get_agent(aid)]
        prompt_cache = await self._prefetch_prompts(retry_agents)

        for agent_id, record in retryable.items():
            agent_node = topology.get_agent(agent_id)
            if not agent_node:
                continue

            record.retries_attempted += 1
            repair_type = "none"

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
                    affected = agent_node.capabilities[0] if agent_node.capabilities else agent_node.name
                    if "Skill '" in record.error_message:
                        try:
                            affected = record.error_message.split("Skill '")[1].split("'")[0]
                        except (IndexError, ValueError):
                            pass
                    gap = CapabilityGap(
                        gap_type=GapType.MISSING_SKILL,
                        severity=GapSeverity.CRITICAL,
                        description=record.error_message[:300],
                        affected_capability=affected,
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
                        topology, _ = await self.topology_loader.reload()
                    else:
                        logger.warning(f"Skill build failed for {record.agent_name}: {build_result.failure_reason}")

                elif record.failure_type == FailureType.LLM_TRANSIENT:
                    repair_type = "simple_retry"

                else:
                    repair_type = "simple_retry"

            except Exception as e:
                logger.error(f"Repair failed for {record.agent_name}: {e}")

            agent_node = topology.get_agent(agent_id)
            if not agent_node:
                continue
            if agent_node.prompt_id and agent_node.prompt_id not in prompt_cache:
                fresh = await self._prefetch_prompts([agent_node])
                prompt_cache.update(fresh)

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
                    result_dict = result if isinstance(result, dict) else {"error": str(result)}
                    record.failure_type = self._classify_failure(result_dict)
                    record.error_message = str(result_dict.get("error", result))
                    logger.warning(f"Retry failed for {record.agent_name}: {record.error_message[:100]}")

                retry_results[record.agent_name] = result

            except Exception as e:
                logger.error(f"Retry execution failed for {record.agent_name}: {e}")
                record.error_message = str(e)
                retry_results[record.agent_name] = {"success": False, "error": str(e)}

        return topology, retry_results


    async def _load_all_agents(self) -> list:
        """Alle aktiven Agents aus DB laden."""
        from app.models.sql.versioned_models import Agent
        async with self._session_factory() as db:
            result = await db.execute(select(Agent).where(Agent.is_active == True))
            return list(result.scalars().all())

    async def _load_all_skills(self) -> list:
        """Alle aktiven Skills aus DB laden."""
        from app.models.sql.versioned_models import Skill
        async with self._session_factory() as db:
            result = await db.execute(select(Skill).where(Skill.is_active == True))
            return list(result.scalars().all())

    async def _handle_team_gaps(self, gap_report: "GapReport") -> None:
        """Delegiert fehlende Capabilities an InterventionOrchestrator."""
        try:
            from app.orchestration.intervention.orchestrator import create_intervention_orchestrator
            intervention = await create_intervention_orchestrator(
                session_factory=self._session_factory,
            )
        except Exception as e:
            logger.warning(f"Kein InterventionOrchestrator für Gap-Handling verfügbar: {e}")
            return

        for missing in gap_report.missing_capabilities:
            try:
                await intervention.build_on_demand(
                    capability=missing.capability,
                    context={
                        "description": missing.description,
                        "rationale": missing.rationale,
                        "suggested_approach": missing.suggested_approach,
                    },
                )
            except Exception as e:
                logger.warning(f"Gap-Build für '{missing.capability}' fehlgeschlagen: {e}")


    async def _write_orchestration_telemetry(
        self,
        phase_tokens: dict[str, int],
        phase_tokens_total: int,
        adapt_rounds: int,
        verification_score: float,
        created_at: datetime,
    ) -> None:
        """OrchestrationTelemetry-Record schreiben (ein INSERT pro Execution)."""
        try:
            from app.models.sql.orchestration_telemetry import OrchestrationTelemetry
            from app.dependencies.dependencies import AsyncSessionLocal
            async with AsyncSessionLocal() as session:
                record = OrchestrationTelemetry(
                    execution_id=self._execution_id,
                    tokens_assembly=phase_tokens["assembly"],
                    tokens_execution=phase_tokens["execution"],
                    tokens_verification=phase_tokens["verification"],
                    tokens_adapt=phase_tokens["adapt"],
                    tokens_self_healing=phase_tokens["self_healing"],
                    tokens_total=phase_tokens_total,
                    adapt_rounds=adapt_rounds,
                    verification_score=round(verification_score * 100),
                    created_at=created_at,
                )
                session.add(record)
                await session.commit()
                logger.info(
                    f"OrchestrationTelemetry: assembly={phase_tokens['assembly']} "
                    f"execution={phase_tokens['execution']} "
                    f"verification={phase_tokens['verification']} "
                    f"adapt={phase_tokens['adapt']} total={phase_tokens_total}"
                )
        except Exception as e:
            logger.warning(f"OrchestrationTelemetry schreiben fehlgeschlagen: {e}")


    def _collect_reflexion_metrics(self, last_verification) -> dict:
        """Sammelt Reflexion-Metriken für Thesis-Auswertung und Ablation."""
        from app.core.config import settings as _cfg
        metrics: dict = {
            "cot_verification_used": _cfg.cot_verification_enabled,
            "self_reflection_triggered": False,
            "self_reflection_correction": 0.0,
            "reflection_tokens_verifier": 0,
            "execution_reflection_enabled": _cfg.execution_reflection_enabled,
        }
        if last_verification:
            metrics["self_reflection_triggered"] = last_verification.score_corrected
            if last_verification.score_corrected and last_verification.original_score is not None:
                metrics["self_reflection_correction"] = round(
                    last_verification.original_score - last_verification.score, 4
                )
            metrics["verification_score"] = last_verification.score
            metrics["aspect_scores"] = last_verification.aspect_scores
        if self._execution_verifier:
            metrics["reflection_tokens_verifier"] = self._execution_verifier._reflection_token_count
        return metrics


    def _extract_final_output(self, results: dict) -> str:
        """Extrahiert den neuesten erfolgreichen Output (nach Einfüge-Reihenfolge)."""
        for wave_key in reversed(list(results.keys())):
            wave_data = results[wave_key]
            if not isinstance(wave_data, dict):
                continue
            for agent_name, agent_result in wave_data.items():
                if isinstance(agent_result, dict) and agent_result.get("success"):
                    result_text = agent_result.get("result", "")
                    if result_text:
                        return str(result_text)[:5000]
        return ""

    def _get_replan_agents(self, waves: list[list[str]]) -> list[str]:
        """Bestimmt welche Agents für Feedback-Retry re-executed werden."""
        if len(waves) <= 1:
            return waves[0] if waves else []
        return [aid for wave in waves[-2:] for aid in wave]

    async def _escalate_to_gap_building(
        self,
        gaps: list[str],
        challenge_text: str,
        previous_output: str = "",
        previous_score: float = 0.0,
    ) -> None:
        """Eskaliert zur Capability-Building-Pipeline bei fundamentalen Gaps."""
        intervention = None
        try:
            from app.orchestration.intervention.orchestrator import create_intervention_orchestrator
            intervention = await create_intervention_orchestrator(
                session_factory=self._session_factory,
            )
        except Exception as e:
            logger.warning(f"Kein InterventionOrchestrator für Eskalation verfügbar: {e}")
            return

        for gap_description in gaps:
            try:
                await intervention.build_on_demand(
                    capability=gap_description,
                    context={
                        "challenge_text": challenge_text[:500],
                        "escalation_reason": "Verify-Adapt Eskalation: Score < 0.1 oder Capability-Gap",
                        "previous_output": previous_output,
                        "previous_score": previous_score,
                    },
                )
            except Exception as e:
                logger.warning(f"Eskalations-Build für '{gap_description}' fehlgeschlagen: {e}")

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
            outcome = "successful" if success else "failed"
            input_summary = ""
            if input_data:
                transcript = input_data.get("transcript") or input_data.get("challenge_text") or ""
                input_summary = transcript[:500] if transcript else str(input_data)[:500]

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
                            for key in ("final_report", "report", "result", "summary"):
                                if key in output and output[key]:
                                    agent_outputs.append((agent_name, key, str(output[key])))
                                    break

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
            from app.orchestration.execution.executor import AutonomousExecutorService

            executor = AutonomousExecutorService(
                db=self.db,
                enable_auto_build=True,
                enable_caching=True,
            )

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


async def _run_evolution_loop_safely(
    execution_id: str,
    agent_id: str = "unknown",
    input_data: Optional[dict] = None,
    tokens_input: int = 0,
    tokens_output: int = 0,
    outcome: str = "success",
    error_message: Optional[str] = None,
    failed_tool_calls: Optional[list[dict]] = None,
) -> None:
    """Run EvolutionLoopService with an isolated DB session.

    Erstellt zuerst die fehlende ExecutionTelemetry-Row (Bridge zwischen
    Execution-Tabelle und AnalysisPipeline), dann startet die Evolution-Loop.
    """
    from app.dependencies.dependencies import AsyncSessionLocal
    from app.dependencies.evolution_loop import build_evolution_loop_service
    from app.repositories.telemetry_repository import TelemetryRepository
    from app.core.telemetry import TelemetryService

    async with AsyncSessionLocal() as session:
        telemetry_repo = TelemetryRepository(session)
        telemetry_svc = TelemetryService(telemetry_repo)
        try:
            telemetry = await telemetry_svc.start_execution(
                agent_id=agent_id,
                execution_id=execution_id,
                input_data=input_data or {},
                metadata={"source": "hybrid_orchestrator"},
            )
            output_data = {}
            if failed_tool_calls:
                output_data["failed_tool_calls"] = failed_tool_calls
            await telemetry_svc.complete_execution(
                telemetry_id=telemetry.id,
                output_data=output_data,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                outcome=outcome,
                error_message=error_message,
            )
            await session.commit()
        except Exception as e:
            logger.warning(f"Telemetrie-Bridge fehlgeschlagen: {e}")
            await session.rollback()

        tool_error_context = ""
        if failed_tool_calls:
            lines = [f"- {tc['tool']}: {tc['error']}" for tc in failed_tool_calls[:10]]
            tool_error_context = "Fehlgeschlagene Tool-Calls während Execution:\n" + "\n".join(lines)

        service = build_evolution_loop_service(session)
        await service.run_post_execution_evolution(
            execution_id,
            output_content=tool_error_context or None,
        )


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
