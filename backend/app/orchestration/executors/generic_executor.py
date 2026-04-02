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
    ToolCallDetector,
    ToolResult,
    build_tool_prompt_section,
    format_tool_result_for_llm,
    MAX_TOOL_CALLS,
)
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.orchestration.topology.loader import TopologyLoader

logger = logging.getLogger(__name__)


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
        sandbox_executor: Optional[Any] = None  # SandboxExecutorService for skill execution
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
        skills = self._get_agent_skills(agent)

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
                execution_id=execution_id
            )
        except Exception as e:
            logger.error(f"Agent {agent.name} execution failed: {e}")
            output = {"error": str(e), "success": False}

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
            }

        # 5. Write to artifacts (session-scoped)
        await self._write_artifacts(agent, output, execution_id)

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
        execution_id: str
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
            skills: Available skills for this agent
            execution_id: Current execution ID

        Returns:
            Final agent output dict
        """
        messages = [
            {"role": "system", "content": f"You are {agent.name}. {', '.join(agent.capabilities)}"},
            {"role": "user", "content": full_prompt}
        ]

        tool_call_count = 0
        tool_results_log: list[dict] = []

        while tool_call_count < MAX_TOOL_CALLS:
            # Call LLM
            response = await self._call_llm_messages(messages, agent)

            # Try to detect tool call in response
            agent_response = self.tool_detector.detect_from_text(response)

            if agent_response is None:
                # No structured response detected - treat as final answer
                logger.debug(f"No structured response detected, treating as final answer")
                return self._parse_response(response, agent)

            if agent_response.is_final_answer():
                # Final answer - return the response
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
                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": format_tool_result_for_llm(tool_result)
                })

        # Max tool calls reached
        logger.warning(f"Agent {agent.name} reached max tool calls ({MAX_TOOL_CALLS})")
        return {
            "result": "Max tool calls reached without final answer",
            "success": False,
            "tool_calls": tool_results_log
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
            return ToolResult(
                tool=tool_name,
                success=False,
                error=f"Tool '{tool_name}' not found",
                execution_time_ms=(time.time() - start_time) * 1000
            )

        code = skill.get("code")
        if not code:
            return ToolResult(
                tool=tool_name,
                success=False,
                error=f"Tool '{tool_name}' has no executable code",
                execution_time_ms=(time.time() - start_time) * 1000
            )

        # Extract function name from code (first function definition)
        import re
        func_match = re.search(r"def\s+(\w+)\s*\(", code)
        function_name = func_match.group(1) if func_match else "execute"

        # Get skill requirements from metadata (for DynamicSandbox)
        skill_metadata = skill.get("metadata", {})
        pip_requirements = skill_metadata.get("pip_requirements", [])
        system_packages = skill_metadata.get("system_packages", [])

        # Execute in sandbox (with fallback to AST-based executor)
        if self.sandbox_executor:
            try:
                result = await self.sandbox_executor.execute_skill(
                    code=code,
                    function_name=function_name,
                    arguments=arguments,
                    pip_requirements=pip_requirements,
                    system_packages=system_packages,
                )
                return ToolResult(
                    tool=tool_name,
                    success=result.success,
                    output=json.loads(result.stdout) if result.success and result.stdout else result.output,
                    error=result.error,
                    execution_time_ms=result.execution_time_ms
                )
            except Exception as e:
                logger.warning(f"Sandbox execution failed for {tool_name}: {e}, falling back to AST executor")
                # Fall through to AST-based executor below

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

    def _get_agent_skills(self, agent: AgentNode) -> list[dict[str, Any]]:
        """
        Get skills for agent from TopologyLoader's eagerly loaded cache.

        Per CONTEXT: Skills loaded eagerly at topology load time, not lazy.
        """
        if not self.topology_loader or not agent.skill_ids:
            return []

        skills = []
        for skill_id in agent.skill_ids:
            skill = self.topology_loader.get_loaded_skill(skill_id)
            if skill:
                # Extract metadata for sandbox execution
                skill_meta = skill.skill_metadata or {}

                # Format skill as LLM tool with execution metadata
                skill_tool = {
                    "name": skill.name,
                    "description": skill.description or f"Skill: {skill.name}",
                    "parameters": skill_meta.get("input", {}),
                    "skill_id": skill.id,
                    "code": skill.code,
                    # Include metadata for DynamicSandbox (pip/apt requirements)
                    "metadata": {
                        "pip_requirements": skill_meta.get("pip_requirements", []),
                        "system_packages": skill_meta.get("system_packages", []),
                    }
                }
                skills.append(skill_tool)
            else:
                logger.warning(f"Skill {skill_id} not found in TopologyLoader cache for agent {agent.agent_id}")

        logger.debug(f"Loaded {len(skills)} skills for agent {agent.name}: {[s['name'] for s in skills]}")
        return skills

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
                query = SharedMemoryQuery(
                    query_text=f"Context for {agent.name} agent",
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
        skills: list[dict[str, Any]]
    ) -> str:
        """Call LLM with prompt and optional tools from skills."""
        # Use agent config for LLM parameters if available
        temperature = agent.config.get("temperature", 0.2)
        max_tokens = agent.config.get("max_tokens", 8192)

        messages = [
            {"role": "system", "content": f"You are {agent.name}. {', '.join(agent.capabilities)}"},
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
                logger.warning(f"Artifact validation failed: {e}")

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
