"""Generic Agent Executor - runs any agent from database definition."""
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional, TYPE_CHECKING

from app.orchestration.topology.models import AgentNode
from app.orchestration.artifacts.models import Artifact
from app.orchestration.artifacts.pool import ArtifactPool
from app.orchestration.shared_memory.service import SharedMemoryService
from app.orchestration.context_manager import ContextBudgetManager
from app.models.schemas.shared_memory_schemas import FactCreate
from app.orchestration.executors.tool_calling import (
    AgentResponse,
    ToolCallDetector,
    ToolCallRequest,
    ToolResult,
    build_tool_prompt_section,
    format_tool_result_for_llm,
    MAX_TOOL_CALLS,
)
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.orchestration.topology.loader import TopologyLoader

logger = logging.getLogger(__name__)

# Map JSON Schema type strings to Python types for Pydantic validation
_SCHEMA_TYPE_MAP: dict[str, type] = {
    "string": str, "str": str,
    "integer": int, "int": int,
    "number": float, "float": float,
    "boolean": bool, "bool": bool,
    "object": dict, "dict": dict,
    "array": list, "list": list,
    "file": str,
}


class ArtifactWriteError(Exception):
    """Raised when artifact validation/write fails."""
    def __init__(self, agent_id: str, artifact_type: str, detail: str):
        self.agent_id = agent_id
        self.artifact_type = artifact_type
        super().__init__(f"Artifact write failed for {agent_id}/{artifact_type}: {detail}")


class GenericAgentExecutor:
    """
    Executes any agent from database definition.

    Replaces agent-specific Python code with generic execution:
    - Prompt loaded from database
    - Skills loaded dynamically from TopologyLoader cache
    - Artifacts and shared memory for data flow
    - Context budget enforced

    Per CONTEXT: All behavior comes from prompts + skills, not hardcoded.
    """

    def __init__(
        self,
        llm_client: Any,  # LLM client with completion method
        artifact_pool: ArtifactPool,
        topology_loader: "TopologyLoader",
        shared_memory: Optional[SharedMemoryService] = None,
        context_manager: Optional[ContextBudgetManager] = None,
        max_context_tokens: int = 100000,
        db: Optional[AsyncSession] = None,  # For auto-creating skills
        sandbox_executor: Optional[Any] = None,  # SandboxExecutorService for skill execution
        intervention_orchestrator: Optional[Any] = None,  # For self-healing skill builds
    ):
        """
        Initialize generic executor.

        Args:
            llm_client: LLM client for agent reasoning
            artifact_pool: Session artifact pool
            shared_memory: Shared memory service (optional)
            context_manager: Context budget manager
            topology_loader: TopologyLoader for skill injection (required)
            max_context_tokens: Max tokens for context window
            db: Database session for auto-creating skills
            sandbox_executor: SandboxExecutorService for secure skill execution
        """
        self.llm_client = llm_client
        self.artifact_pool = artifact_pool
        self.shared_memory = shared_memory
        self.context_manager = context_manager or ContextBudgetManager()
        self.topology_loader = topology_loader
        self.max_context_tokens = max_context_tokens
        self.db = db  # For auto-creating skills
        self.sandbox_executor = sandbox_executor
        self._intervention = intervention_orchestrator
        self._self_healing_count = 0     # Track builds per execution
        self._in_self_healing = False    # Recursion guard
        self.tool_detector = ToolCallDetector()

    async def execute(
        self,
        agent: AgentNode,
        prompt_content: str,
        execution_id: str,
        input_data: Optional[dict] = None,
        project_id: str = "default"
    ) -> dict[str, Any]:
        """
        Execute an agent with generic logic and tool calling loop.

        1. Build context from shared memory + artifacts
        2. Load skills from TopologyLoader cache
        3. Construct prompt with context and skills
        4. Call LLM - if tool call detected, execute skill and loop (max 5 times)
        5. Write output to artifacts AND shared memory
        6. Return result

        Args:
            agent: Agent definition from topology
            prompt_content: Prompt template from database
            execution_id: Current execution run ID
            input_data: Optional direct input (overrides artifacts)

        Returns:
            Agent output dict
        """
        logger.info(f"Executing agent: {agent.name} ({agent.agent_id})")

        # 1. Build context
        context = await self._build_context(agent, execution_id)

        # 2. Load skills from TopologyLoader cache (per CONTEXT: eager loading)
        skills, planning_skills = self._get_agent_skills(agent)

        # 3. Construct prompt with tool calling format if skills available
        full_prompt = self._construct_prompt(
            prompt_content=prompt_content,
            context=context,
            input_data=input_data,
            agent=agent,
            skills=skills
        )

        # 4. Tool calling loop - call LLM, detect tool calls, execute, repeat
        try:
            output = await self._execute_with_tool_loop(
                full_prompt=full_prompt,
                agent=agent,
                skills=skills,
                planning_skills=planning_skills,
                execution_id=execution_id
            )
        except Exception as e:
            logger.error(f"Agent {agent.name} execution failed: {e}")
            output = {"error": str(e), "success": False, "failure_type": "llm_error"}

        # 4.5 Graceful degradation: if agent says it can't handle the input, skip gracefully
        output_str = json.dumps(output) if isinstance(output, dict) else str(output)
        refusal_patterns = [
            "cannot fulfill the request",
            "not in the format",
            "not relevant to my task",
            "I am sorry, but I cannot",
        ]
        if any(p.lower() in output_str.lower() for p in refusal_patterns):
            logger.warning(
                f"Agent {agent.name} cannot process input — skipping gracefully. "
                f"Response: {output_str[:200]}"
            )
            output = {
                "skipped": True,
                "reason": f"Agent {agent.name} cannot process this input format",
                "success": False,
                "failure_type": "agent_refusal",
            }

        # 5. Write to artifacts (session-scoped)
        try:
            await self._write_artifacts(agent, output, execution_id)
        except ArtifactWriteError as e:
            logger.error(f"Agent {agent.name} artifact write failed: {e}")
            output = {"error": str(e), "success": False, "failure_type": "artifact_validation"}

        # 6. Write to shared memory (long-term)
        if self.shared_memory:
            await self._write_to_shared_memory(agent, output, execution_id, project_id)

        # 7. Auto-create skill if tool_builder produced code
        if agent.name == "tool_builder" and "code" in output and self.db:
            await self._auto_create_skill(output, execution_id)

        logger.info(f"Agent {agent.name} completed")
        return output

    async def _execute_with_tool_loop(
        self,
        full_prompt: str,
        agent: AgentNode,
        skills: list[dict[str, Any]],
        execution_id: str,
        planning_skills: Optional[list[dict[str, Any]]] = None
    ) -> dict[str, Any]:
        """
        Execute LLM with tool calling loop.

        Iteratively calls LLM and executes tools until:
        - LLM returns final_answer
        - Max tool calls reached (5)
        - Error occurs

        Args:
            full_prompt: Initial prompt with context and tool docs
            agent: Agent definition
            skills: Available functional skills for this agent
            execution_id: Current execution ID
            planning_skills: Planning skills to inject into system prompt

        Returns:
            Final agent output dict
        """
        planning_context = self._build_planning_prompt(planning_skills or [])
        messages = [
            {"role": "system", "content": f"You are {agent.name}.{planning_context}"},
            {"role": "user", "content": full_prompt}
        ]

        tool_call_count = 0
        tool_results_log: list[dict] = []

        while tool_call_count < MAX_TOOL_CALLS:
            # Call LLM with Instructor for structured, validated output
            try:
                agent_response = await self.llm_client.chat_structured(
                    messages=messages,
                    response_model=AgentResponse,
                    temperature=agent.config.get("temperature", 0.2),
                    max_tokens=agent.config.get("max_tokens", 8192),
                    max_retries=2,
                )
            except Exception as e:
                # Fallback to raw text parsing if chat_structured fails
                logger.warning(f"chat_structured failed, falling back to text parsing: {e}")
                response = await self._call_llm_messages(messages, agent)
                agent_response = self.tool_detector.detect_from_text(response)
                if agent_response is None:
                    return self._parse_response(response, agent)

            if agent_response.is_final_answer():
                logger.info(f"Agent {agent.name} returned final answer after {tool_call_count} tool calls")
                return {
                    "result": agent_response.response or "",
                    "success": True,
                    "tool_calls": tool_results_log
                }

            if agent_response.is_tool_call():
                tool_call = agent_response.to_tool_call()
                if not tool_call:
                    logger.warning("Failed to parse tool call request")
                    return {"error": "Invalid tool call format", "success": False}

                # Validate and fix arguments against skill interface schema
                tool_call = await self._validate_and_fix_arguments(tool_call, skills)

                tool_call_count += 1
                logger.info(f"Tool call {tool_call_count}/{MAX_TOOL_CALLS}: {tool_call.tool}")

                # Execute the tool
                tool_result = await self._execute_tool(
                    tool_name=tool_call.tool,
                    arguments=tool_call.arguments,
                    skills=skills,
                    execution_id=execution_id
                )

                tool_results_log.append({
                    "tool": tool_call.tool,
                    "arguments": tool_call.arguments,
                    "result": {
                        "success": tool_result.success,
                        "output": tool_result.output,
                        "error": tool_result.error,
                        "execution_time_ms": tool_result.execution_time_ms
                    }
                })

                # Add assistant's response and tool result to messages
                messages.append({"role": "assistant", "content": agent_response.model_dump_json()})
                messages.append({
                    "role": "user",
                    "content": format_tool_result_for_llm(tool_result)
                })

        # Max tool calls reached
        logger.warning(f"Agent {agent.name} reached max tool calls ({MAX_TOOL_CALLS})")
        return {
            "result": "Max tool calls reached without final answer",
            "success": False,
            "failure_type": "tool_error",
            "tool_calls": tool_results_log,
        }

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        skills: list[dict[str, Any]],
        execution_id: str
    ) -> ToolResult:
        """
        Execute a skill/tool by name.

        Finds the skill code and runs it in the sandbox.

        Args:
            tool_name: Name of the tool/skill to execute
            arguments: Arguments to pass to the skill
            skills: Available skills list
            execution_id: Current execution ID

        Returns:
            ToolResult with success status and output/error
        """
        start_time = time.time()

        # Find the skill
        skill = next((s for s in skills if s["name"] == tool_name), None)
        if not skill:
            # Attempt self-healing if enabled
            from app.core.config import settings
            if (settings.intra_execution_self_healing_enabled
                    and self._intervention
                    and self._self_healing_count < settings.self_healing_max_builds_per_execution
                    and not self._in_self_healing):
                built = await self._self_heal_missing_tool(tool_name, arguments, skills)
                if built:
                    skill = built
                else:
                    return ToolResult(
                        tool=tool_name, success=False,
                        error=f"Tool '{tool_name}' not found (self-healing failed)",
                        execution_time_ms=(time.time() - start_time) * 1000,
                    )
            else:
                return ToolResult(
                    tool=tool_name, success=False,
                    error=f"Tool '{tool_name}' not found",
                    execution_time_ms=(time.time() - start_time) * 1000,
                )

        code = skill.get("code")
        if not code:
            return ToolResult(
                tool=tool_name,
                success=False,
                error=f"Tool '{tool_name}' has no executable code",
                execution_time_ms=(time.time() - start_time) * 1000
            )

        # Extract function name from code (standard: "execute")
        import re, os
        func_match = re.search(r"def\s+(\w+)\s*\(", code)
        function_name = func_match.group(1) if func_match else "execute"

        # Get skill requirements from metadata (for DynamicSandbox)
        skill_metadata = skill.get("metadata", {})
        pip_requirements = skill_metadata.get("pip_requirements", [])
        system_packages = skill_metadata.get("system_packages", [])
        logger.debug(f"Skill {tool_name}: pip={pip_requirements}, sys={system_packages}")

        # Identify file parameters from skill interface schema
        skill_interface = skill.get("interface") or {}
        input_props = skill_interface.get("input", {}).get("properties", {})
        file_params = {
            k for k, v in input_props.items()
            if isinstance(v, dict) and (
                v.get("type") == "file"
                or (v.get("type") == "array" and isinstance(v.get("items"), dict)
                    and v["items"].get("type") == "file")
            )
        }

        # Fallback for skills without interface: name-based detection
        if not file_params:
            file_params = {
                k for k in arguments
                if isinstance(arguments.get(k), str)
                and ("file_path" in k or "path" in k)
            }

        # Collect input_files: read referenced files so sandbox can access them
        input_files: dict[str, bytes] = {}
        sandbox_arguments = dict(arguments)

        # Also check actual argument keys that look like file paths but aren't in file_params
        # (agent may use slightly different key names than the interface defines)
        for k, v in arguments.items():
            if k not in file_params and isinstance(v, str) and (
                "file" in k or "path" in k
            ):
                file_params.add(k)

        logger.debug(f"File detection: file_params={file_params}, arguments_keys={list(arguments.keys())}")
        for arg_key in file_params:
            arg_val = arguments.get(arg_key)
            if not isinstance(arg_val, str):
                continue

            # Resolve host-side path (may be /workspace/... referencing uploads dir)
            host_path = arg_val
            if arg_val.startswith("/workspace/"):
                upload_dir = os.path.join(
                    os.path.dirname(__file__), '..', '..', '..', 'uploads'
                )
                host_path = os.path.join(upload_dir, os.path.basename(arg_val))

            if os.path.isfile(host_path):
                filename = os.path.basename(host_path)
                with open(host_path, "rb") as f:
                    input_files[filename] = f.read()
                sandbox_arguments[arg_key] = f"/workspace/{filename}"
                logger.info(f"Providing file to sandbox: {filename} ({len(input_files[filename])} bytes)")

        # Execute in sandbox via execute_skill (supports input_files)
        if self.sandbox_executor and hasattr(self.sandbox_executor, 'execute_skill'):
            try:
                result = await self.sandbox_executor.execute_skill(
                    code=code,
                    function_name=function_name,
                    arguments=sandbox_arguments,
                    pip_requirements=pip_requirements,
                    system_packages=system_packages,
                    input_files=input_files if input_files else None,
                )
                return ToolResult(
                    tool=tool_name,
                    success=result.success,
                    output=result.output,
                    error=result.error,
                    execution_time_ms=result.execution_time_ms
                )
            except Exception as e:
                logger.warning(f"Sandbox execution failed for {tool_name}: {e}, falling back to AST executor")
        elif self.sandbox_executor:
            try:
                # Fallback: execute() proxy (no input_files support)
                args_json = json.dumps(sandbox_arguments)
                runner_code = (
                    f"{code}\n\n"
                    f"import json, sys\n"
                    f"_args = json.loads({repr(args_json)})\n"
                    f"_result = {function_name}(_args)\n"
                    f"print(json.dumps(_result))\n"
                )
                result = await self.sandbox_executor.execute(
                    code=runner_code,
                    pip_requirements=pip_requirements,
                    system_packages=system_packages,
                )
                output = None
                if result.success and result.stdout:
                    try:
                        output = json.loads(result.stdout.strip())
                    except json.JSONDecodeError:
                        output = result.stdout.strip()
                return ToolResult(
                    tool=tool_name,
                    success=result.success,
                    output=output,
                    error=result.error,
                    execution_time_ms=result.execution_time_ms
                )
            except Exception as e:
                logger.warning(f"Sandbox execution failed for {tool_name}: {e}, falling back to AST executor")

        # Fallback: Use SkillExecutor (AST-based) if no sandbox or sandbox failed
        try:
            from app.services.skill_executor import SkillExecutor
            executor = SkillExecutor(timeout_seconds=5.0)
            result = await executor.execute_code(
                code=code,
                input_data=arguments,
                function_name=function_name
            )
            return ToolResult(
                tool=tool_name,
                success=result.success,
                output=result.output,
                error=result.error,
                execution_time_ms=result.execution_time_ms
            )
        except Exception as e:
            logger.error(f"Skill execution failed for {tool_name}: {e}")
            return ToolResult(
                tool=tool_name,
                success=False,
                error=f"Skill execution failed: {e}",
                execution_time_ms=(time.time() - start_time) * 1000
            )

    async def _call_llm_messages(
        self,
        messages: list[dict[str, str]],
        agent: AgentNode
    ) -> str:
        """Call LLM with message history (for tool calling loop)."""
        temperature = agent.config.get("temperature", 0.2)
        max_tokens = agent.config.get("max_tokens", 8192)

        response = await self.llm_client.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )

        return response.content

    async def _self_heal_missing_tool(
        self,
        tool_name: str,
        arguments: dict,
        skills: list[dict],
    ) -> Optional[dict]:
        """Attempt to build a missing tool on-the-fly via InterventionOrchestrator."""
        import asyncio
        from app.core.config import settings

        logger.info(f"Self-healing: attempting to build missing tool '{tool_name}'")
        self._in_self_healing = True
        self._self_healing_count += 1
        try:
            build_result = await asyncio.wait_for(
                self._intervention.build_on_demand(
                    capability=tool_name,
                    context=arguments,
                ),
                timeout=float(settings.self_healing_build_timeout),
            )
            if build_result and build_result.success:
                new_tool = self._build_result_to_tool_dict(build_result, tool_name)
                skills.append(new_tool)
                logger.info(f"Self-healing successful: built tool '{tool_name}'")
                return new_tool
            logger.warning(f"Self-healing build failed for '{tool_name}'")
            return None
        except asyncio.TimeoutError:
            logger.warning(f"Self-healing build timed out for '{tool_name}'")
            return None
        except Exception as e:
            logger.error(f"Self-healing failed for '{tool_name}': {e}")
            return None
        finally:
            self._in_self_healing = False

    @staticmethod
    def _build_result_to_tool_dict(build_result: Any, tool_name: str) -> dict:
        """Convert a build result to the tool dict format used by skills list."""
        return {
            "name": build_result.skill_name or tool_name,
            "description": f"Auto-built skill for: {tool_name}",
            "parameters": {},
            "skill_id": build_result.skill_id or "",
            "code": build_result.final_code or "",
            "metadata": {
                "pip_requirements": (build_result.requirements_txt or "").split("\n") if build_result.requirements_txt else [],
                "system_packages": [],
                "self_healed": True,
            },
        }

    async def _validate_and_fix_arguments(
        self, tool_call: ToolCallRequest, skills: list[dict]
    ) -> ToolCallRequest:
        """Validate tool arguments against skill interface schema, fix via Instructor re-prompt."""
        skill = next((s for s in skills if s["name"] == tool_call.tool), None)
        if not skill:
            return tool_call

        iface = (skill.get("interface") or {}).get("input", {})
        props = iface.get("properties", {})
        if not props:
            return tool_call

        # Build dynamic Pydantic model from interface schema
        from pydantic import create_model as pydantic_create_model
        fields: dict[str, Any] = {}
        for name, schema in props.items():
            if not isinstance(schema, dict):
                continue
            st = schema.get("type", "string")
            ptype = _SCHEMA_TYPE_MAP.get(st, str)
            required_keys = iface.get("required", [])
            if name in required_keys:
                fields[name] = (ptype, ...)
            else:
                fields[name] = (Optional[ptype], None)

        if not fields:
            return tool_call

        DynamicArgs = pydantic_create_model(f"{tool_call.tool}_Args", **fields)

        # Step 1: Try to validate current arguments directly
        try:
            validated = DynamicArgs(**tool_call.arguments)
            tool_call.arguments = validated.model_dump(exclude_none=True)
            return tool_call
        except Exception:
            pass

        # Step 2: Re-prompt via Instructor — LLM gets the exact schema and fixes the arguments
        logger.info(f"Arguments invalid for {tool_call.tool}, re-prompting via Instructor")
        fix_prompt = (
            f"You called tool '{tool_call.tool}' with arguments: {json.dumps(tool_call.arguments)}\n"
            f"But the tool expects these exact parameters:\n{json.dumps(props, indent=2)}\n"
            f"Provide the corrected arguments with the correct parameter names and types. "
            f"Map the values from the original arguments to the correct parameter names."
        )
        try:
            fixed = await self.llm_client.chat_structured(
                messages=[{"role": "user", "content": fix_prompt}],
                response_model=DynamicArgs,
                max_retries=2,
            )
            tool_call.arguments = fixed.model_dump(exclude_none=True)
            logger.info(f"Fixed arguments for {tool_call.tool} via Instructor re-prompt")
        except Exception as e:
            logger.warning(f"Instructor re-prompt failed for {tool_call.tool}: {e}")

        return tool_call

    def _get_agent_skills(self, agent: AgentNode) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Get skills for agent from TopologyLoader's eagerly loaded cache.

        Returns:
            Tuple of (functional_skills, planning_skills).
            Functional skills are offered as tools in the tool-calling loop.
            Planning skills are injected into the system prompt as reasoning guidelines.
        """
        if not self.topology_loader or not agent.skill_ids:
            return [], []

        functional_skills = []
        planning_skills = []

        for skill_id in agent.skill_ids:
            skill = self.topology_loader.get_loaded_skill(skill_id)
            if not skill:
                logger.warning(f"Skill {skill_id} not found in TopologyLoader cache for agent {agent.agent_id}")
                continue

            skill_type = getattr(skill, 'skill_type', 'functional') or 'functional'

            if skill_type == "planning":
                planning_skills.append({
                    "name": skill.name,
                    "applicability": getattr(skill, 'applicability', '') or '',
                    "instructions": getattr(skill, 'instructions', '') or '',
                    "termination": getattr(skill, 'termination', '') or '',
                })
            else:
                # Functional skill — offer as tool
                skill_meta = skill.skill_metadata or {}
                skill_interface = getattr(skill, 'interface', None) or {}
                functional_skills.append({
                    "name": skill.name,
                    "description": getattr(skill, 'applicability', None) or skill.description or f"Skill: {skill.name}",
                    "parameters": skill_interface.get("input", skill_meta.get("input", {})),
                    "interface": skill_interface,
                    "skill_id": skill.id,
                    "code": skill.code,
                    "metadata": {
                        "pip_requirements": skill_meta.get("pip_requirements", []),
                        "system_packages": skill_meta.get("system_packages", []),
                    }
                })

        if functional_skills:
            logger.debug(f"Agent {agent.name}: {len(functional_skills)} functional skills: {[s['name'] for s in functional_skills]}")
        if planning_skills:
            logger.debug(f"Agent {agent.name}: {len(planning_skills)} planning skills: {[s['name'] for s in planning_skills]}")

        return functional_skills, planning_skills

    @staticmethod
    def _build_planning_prompt(planning_skills: list[dict[str, Any]]) -> str:
        """Build system prompt section from planning skills."""
        if not planning_skills:
            return ""

        sections = ["\n\n## Reasoning Guidelines"]
        for ps in planning_skills:
            sections.append(f"\n### {ps['name']}")
            if ps['applicability']:
                sections.append(f"When to apply: {ps['applicability']}")
            if ps['instructions']:
                sections.append(ps['instructions'])
            if ps['termination']:
                sections.append(f"Done when: {ps['termination']}")

        return "\n".join(sections)

    async def _build_context(
        self,
        agent: AgentNode,
        execution_id: str
    ) -> dict[str, Any]:
        """
        Build context for agent from artifacts and shared memory.

        Respects context budget.
        """
        context: dict[str, Any] = {
            "artifacts": [],
            "shared_memory": [],
            "metadata": {
                "execution_id": execution_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        }

        # Get artifacts this agent consumes
        if agent.consumes_artifacts:
            artifacts = await self.artifact_pool.read(agent.consumes_artifacts)
            context["artifacts"] = [
                {"type": a.artifact_type, "payload": a.payload, "source": a.source_agent_id}
                for a in artifacts
            ]

        # Get shared memory context
        if self.shared_memory:
            try:
                from app.models.schemas.shared_memory_schemas import SharedMemoryQuery
                # Build query from artifacts content (task-relevant) instead of generic agent name
                query_text = f"Context for {agent.name} agent"
                if context["artifacts"]:
                    # Use artifact content for semantic search — finds related past executions
                    artifact_texts = []
                    for a in context["artifacts"][:3]:
                        payload = a.get("payload", {})
                        for key in ("transcript", "challenge_text", "text", "summary", "key_points"):
                            if key in payload and payload[key]:
                                artifact_texts.append(str(payload[key])[:300])
                                break
                    if artifact_texts:
                        query_text = " ".join(artifact_texts)
                query = SharedMemoryQuery(
                    query_text=query_text,
                    agent_id=None,  # Get from all agents
                    max_items=30
                )
                memory = await self.shared_memory.retrieve_context(
                    query=query,
                    max_tokens=self.max_context_tokens // 2
                )
                context["shared_memory"] = memory.get("facts", [])[:20]
            except Exception as e:
                logger.warning(f"Failed to retrieve shared memory: {e}")

        # Apply context budget
        budget = self.context_manager.allocate_context(self.max_context_tokens)
        context["_budget"] = budget

        return context

    def _construct_prompt(
        self,
        prompt_content: str,
        context: dict[str, Any],
        input_data: Optional[dict],
        agent: AgentNode,
        skills: list[dict[str, Any]]
    ) -> str:
        """
        Construct full prompt with context injection and skill descriptions.

        Template variables:
        - {context}: Full context as JSON
        - {artifacts}: Artifacts as JSON
        - {shared_memory}: Shared memory as JSON
        - {input}: Direct input as JSON
        - {skills}: Available skills as JSON
        """
        # Format context sections
        artifacts_json = json.dumps(context["artifacts"], indent=2)
        memory_json = json.dumps(context["shared_memory"], indent=2)
        input_json = json.dumps(input_data or {}, indent=2)
        skills_json = json.dumps([{"name": s["name"], "description": s["description"]} for s in skills], indent=2)

        # Replace template variables
        prompt = prompt_content
        prompt = prompt.replace("{context}", json.dumps(context, indent=2))
        prompt = prompt.replace("{artifacts}", artifacts_json)
        prompt = prompt.replace("{shared_memory}", memory_json)
        prompt = prompt.replace("{input}", input_json)
        prompt = prompt.replace("{skills}", skills_json)

        # Add output schema hint if defined (only if no skills - skills use tool format)
        if agent.output_schema and not skills:
            prompt += f"\n\nOutput must conform to this schema:\n{json.dumps(agent.output_schema, indent=2)}"

        # Add tool calling section if skills available
        if skills:
            tool_prompt = build_tool_prompt_section(skills)
            prompt += tool_prompt

        # Append raw input data ONLY to entry-point agents (no dependencies, no consumed artifacts)
        # Agents that consume artifacts from previous waves should NOT get raw input —
        # they work with processed data from upstream agents.
        is_entry_point = not agent.dependencies and not agent.consumes_artifacts
        if input_data and is_entry_point:
            if "challenge" in input_data:
                prompt += f"\n\n=== INPUT TO ANALYZE ===\n{input_data['challenge']}"
            elif "transcript" in input_data:
                prompt += f"\n\n=== TRANSCRIPT TO ANALYZE ===\n{input_data['transcript']}"
            else:
                prompt += f"\n\n=== INPUT DATA ===\n{json.dumps(input_data, indent=2)}"

        return prompt

    async def _call_llm(
        self,
        prompt: str,
        agent: AgentNode,
        skills: list[dict[str, Any]],
        planning_skills: Optional[list[dict[str, Any]]] = None
    ) -> str:
        """Call LLM with prompt and optional tools from skills."""
        # Use agent config for LLM parameters if available
        temperature = agent.config.get("temperature", 0.2)
        max_tokens = agent.config.get("max_tokens", 8192)

        planning_context = self._build_planning_prompt(planning_skills or [])
        messages = [
            {"role": "system", "content": f"You are {agent.name}.{planning_context}"},
            {"role": "user", "content": prompt}
        ]

        # Format skills as LLM tools if available
        tools = None
        if skills:
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": skill["name"],
                        "description": skill["description"],
                        "parameters": skill.get("parameters", {"type": "object", "properties": {}})
                    }
                }
                for skill in skills
            ]

        # Call via LLMClient.chat()
        if tools:
            response = await self.llm_client.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools
            )
        else:
            response = await self.llm_client.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )

        return response.content

    def _parse_response(
        self,
        response: str,
        agent: AgentNode
    ) -> dict[str, Any]:
        """Parse LLM response to dict."""
        # Try to extract JSON from response
        try:
            # Look for JSON block
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0].strip()
                return json.loads(json_str)
            elif response.strip().startswith("{"):
                return json.loads(response)
            else:
                # Wrap plain text in result dict
                return {"result": response, "success": True}
        except json.JSONDecodeError:
            return {"result": response, "success": True}

    async def _write_artifacts(
        self,
        agent: AgentNode,
        output: dict[str, Any],
        execution_id: str
    ) -> None:
        """
        Write output to session artifact pool.

        Per CONTEXT: Validate at write time.
        """
        for artifact_type in agent.produces_artifacts:
            artifact = Artifact(
                artifact_type=artifact_type,
                payload=output,
                source_agent_id=agent.agent_id,
                execution_id=execution_id
            )
            try:
                await self.artifact_pool.write(artifact)
            except ValueError as e:
                logger.error(f"Artifact validation failed: {e}")
                raise ArtifactWriteError(agent.agent_id, artifact_type, str(e))

    async def _write_to_shared_memory(
        self,
        agent: AgentNode,
        output: dict[str, Any],
        execution_id: str,
        project_id: str = "default"
    ) -> None:
        """
        Write key findings to shared memory.

        Per CONTEXT: Agents write to BOTH session and shared memory.
        """
        # Extract facts from output
        facts_to_store: list[dict[str, Any]] = []

        # If output has explicit facts
        if "facts" in output:
            facts_to_store.extend(output["facts"])
        elif "findings" in output:
            facts_to_store.extend(output["findings"])
        elif "result" in output and isinstance(output["result"], str):
            # Store result as single fact
            facts_to_store.append({
                "text": output["result"],
                "confidence": output.get("confidence", 0.8)
            })

        for fact_data in facts_to_store[:10]:  # Limit to 10 facts
            try:
                text = fact_data.get("text", str(fact_data))
                confidence = fact_data.get("confidence", 0.8)

                fact = FactCreate(
                    text=text,
                    confidence=confidence,
                    source_agent_id=agent.agent_id,
                    execution_id=execution_id,
                    project_id=project_id,
                    tags=[agent.name]
                )
                await self.shared_memory.create_fact(fact)
            except Exception as e:
                logger.warning(f"Failed to store fact: {e}")

    async def _auto_create_skill(
        self,
        output: dict[str, Any],
        execution_id: str
    ) -> None:
        """
        Auto-create a skill from tool_builder output.

        Extracts skill data from output and creates via SkillService.
        Skills are created as inactive until tests pass.
        """
        try:
            from app.repositories.skill_repository import SkillRepository
            from app.services.skill_service import SkillService
            import re

            code = output.get("code", "")
            if not code:
                logger.warning("tool_builder output has no code, skipping skill creation")
                return

            # Extract function name from code for skill name
            func_match = re.search(r"def\s+(\w+)\s*\(", code)
            func_name = func_match.group(1) if func_match else "unnamed_skill"

            # Extract docstring for description
            doc_match = re.search(r'"""([^"]+)"""', code)
            description = doc_match.group(1).strip() if doc_match else f"Auto-generated skill: {func_name}"

            # Use provided name/description if available
            skill_name = output.get("name", func_name)
            skill_description = output.get("description", description)

            # Get test cases if provided
            test_cases = output.get("test_cases", [])

            # Check if skill with same name already exists
            repo = SkillRepository(self.db)
            existing = await repo.get_by_name(skill_name)
            if existing:
                logger.info(f"Skill '{skill_name}' already exists (id={existing.id}), skipping creation")
                return

            # Create skill via service
            service = SkillService(repository=repo)
            skill_data = {
                "name": skill_name,
                "description": skill_description,
                "code": code,
                "test_cases": test_cases,
                "is_active": False,  # Start inactive, activate after manual review or test pass
                "skill_metadata": {
                    "source": "auto_created",
                    "execution_id": execution_id,
                    "created_by": "tool_builder"
                }
            }

            skill = await service.create(skill_data, validate=bool(test_cases))
            logger.info(f"Auto-created skill '{skill_name}' (id={skill.id}, active={skill.is_active})")

            # Add skill ID to output for reference
            output["created_skill_id"] = skill.id
            output["created_skill_name"] = skill_name

        except Exception as e:
            logger.error(f"Failed to auto-create skill: {e}")
            output["skill_creation_error"] = str(e)


class AgentExecutionResult:
    """Result of agent execution."""

    def __init__(
        self,
        agent_id: str,
        success: bool,
        output: dict[str, Any],
        duration_ms: int,
        error: Optional[str] = None
    ):
        self.agent_id = agent_id
        self.success = success
        self.output = output
        self.duration_ms = duration_ms
        self.error = error
