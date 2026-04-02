"""
Improvement Orchestrator Service for executing approved improvements.

This service orchestrates the flow from Control Agent decision to A/B test:
1. Receives approved ImprovementAction from ControlAgentService
2. Routes prompt improvements to PromptEngineerService (modify_prompt)
3. Routes skill improvements to ToolBuilderService (modify_tool) with sandbox validation
4. Creates A/B test via ABTestService after artifact is modified
5. Tracks improvement attempt status throughout the flow

Flow:
    ControlAgentService.evaluate_findings() -> ImprovementAction
    -> ImprovementOrchestrator.execute_improvement()
    -> PromptEngineerService.modify_prompt() OR ToolBuilderService.modify_tool()
    -> SandboxExecutorService.execute_tests() (for skills)
    -> ABTestService.create_test()
"""
import hashlib
import logging
import re
from typing import Optional

from pydantic import ValidationError

from app.core.llm_client import LLMError
from app.models.schemas.analysis_schemas import Finding
from app.models.schemas.control_schemas import ImprovementAction, ImprovementAttemptCreate
from app.models.schemas.prompt_engineer_schemas import PromptModificationRequest
from app.models.schemas.tool_builder_schemas import ToolModificationRequest
from app.repositories.improvement_repository import ImprovementRepository
from app.repositories.prompt_repository import PromptRepository
from app.repositories.skill_repository import SkillRepository
from app.services.prompt_engineer_service import PromptEngineerService
from app.services.ab_test_service import ABTestService
from app.services.tool_builder_service import ToolBuilderService
from app.services.sandbox_executor_service import SandboxExecutorService

log = logging.getLogger(__name__)


class ImprovementOrchestrator:
    """
    Orchestrates execution of approved improvements from Control Agent.

    Routes improvements to appropriate services (PromptEngineerService for prompts,
    future phases will add AgentBuilderService for agents, etc.) and creates A/B
    tests to validate the changes.

    Example:
        llm_client = LLMClient()
        improvement_repo = ImprovementRepository(session)
        prompt_repo = PromptRepository(session)
        prompt_engineer = PromptEngineerService(llm_client, prompt_repo)
        ab_test_service = ABTestService(...)

        orchestrator = ImprovementOrchestrator(
            improvement_repo=improvement_repo,
            prompt_engineer=prompt_engineer,
            prompt_repo=prompt_repo,
            ab_test_service=ab_test_service
        )

        # Execute improvement from Control Agent
        test_id = await orchestrator.execute_improvement(
            action=approved_action,
            finding=original_finding,
            agent_id="agent-uuid"
        )
    """

    def __init__(
        self,
        improvement_repo: ImprovementRepository,
        prompt_engineer: PromptEngineerService,
        prompt_repo: PromptRepository,
        ab_test_service: ABTestService,
        # Phase 6 dependencies (optional for backward compatibility)
        tool_builder: Optional[ToolBuilderService] = None,
        sandbox_executor: Optional[SandboxExecutorService] = None,
        skill_repo: Optional[SkillRepository] = None,
    ):
        """
        Initialize the Improvement Orchestrator.

        Args:
            improvement_repo: ImprovementRepository for tracking attempts.
            prompt_engineer: PromptEngineerService for prompt generation/modification.
            prompt_repo: PromptRepository for fetching existing prompts.
            ab_test_service: ABTestService for creating A/B tests.
            tool_builder: ToolBuilderService for skill generation/modification (Phase 6).
            sandbox_executor: SandboxExecutorService for skill validation (Phase 6).
            skill_repo: SkillRepository for skill lookup (Phase 6).
        """
        self.improvement_repo = improvement_repo
        self.prompt_engineer = prompt_engineer
        self.prompt_repo = prompt_repo
        self.ab_test_service = ab_test_service
        # Phase 6
        self.tool_builder = tool_builder
        self.sandbox_executor = sandbox_executor
        self.skill_repo = skill_repo

    async def execute_improvement(
        self,
        action: ImprovementAction,
        finding: Finding,
        agent_id: str,
    ) -> Optional[str]:
        """
        Execute an approved improvement action.

        Routes prompt improvements to PromptEngineerService, creates A/B test.

        Args:
            action: Approved ImprovementAction from ControlAgentService.
            finding: Original Finding being addressed.
            agent_id: UUID of agent being improved.

        Returns:
            A/B test ID if created, None if queued or failed.
        """
        log.info(
            f"Executing improvement for artifact_type={action.artifact_type}:"
            f"{action.artifact_id[:8]}..."
        )

        # Generate fingerprint from finding for tracking
        fingerprint = self._generate_fingerprint(finding)

        # Get current attempt count for this finding
        attempt_count = await self.improvement_repo.get_attempt_count(fingerprint)

        # Calculate version_before
        if action.artifact_type == "prompt":
            children = await self.prompt_repo.get_children(action.artifact_id)
            version_before = len(children)
        elif action.artifact_type == "skill" and self.skill_repo:
            children = await self.skill_repo.get_children(action.artifact_id)
            version_before = len(children)
        else:
            # For agents, version tracking TBD in Phase 7
            version_before = 0

        # Create ImprovementAttempt record
        attempt_data = ImprovementAttemptCreate(
            finding_fingerprint=fingerprint,
            artifact_type=action.artifact_type,
            artifact_id=action.artifact_id,
            version_before=version_before,
            attempt_number=attempt_count + 1,
            ab_test_id=None  # Will be set after A/B test creation
        )
        improvement_attempt = await self.improvement_repo.create(attempt_data)

        # Route based on artifact_type
        if action.artifact_type == "prompt":
            return await self._execute_prompt_improvement(
                action=action,
                finding=finding,
                improvement_attempt_id=improvement_attempt.id,
            )
        elif action.artifact_type == "skill":
            if not self.tool_builder or not self.sandbox_executor or not self.skill_repo:
                log.error("Skill improvement requested but Tool Builder not configured")
                return None
            return await self._execute_skill_improvement(
                action=action,
                finding=finding,
                improvement_attempt_id=improvement_attempt.id,
            )
        elif action.artifact_type == "agent":
            log.warning("Agent improvements not yet supported (Phase 7)")
            return None
        else:
            log.error(f"Unknown artifact type: {action.artifact_type}")
            return None

    async def _execute_prompt_improvement(
        self,
        action: ImprovementAction,
        finding: Finding,
        improvement_attempt_id: str,
    ) -> Optional[str]:
        """
        Execute prompt improvement via PromptEngineerService.

        Flow:
        1. Fetch current prompt
        2. Call PromptEngineerService.modify_prompt()
        3. Create A/B test
        4. Handle errors gracefully

        Args:
            action: ImprovementAction from Control Agent.
            finding: Original Finding being addressed.
            improvement_attempt_id: UUID of the improvement attempt record.

        Returns:
            A/B test ID if created, None if queued or failed.
        """
        try:
            # Fetch current prompt
            current_prompt = await self.prompt_repo.get_by_id(action.artifact_id)
            if not current_prompt:
                log.error(f"Prompt not found: id={action.artifact_id}")
                await self.improvement_repo.update_status(
                    improvement_attempt_id,
                    status='failed',
                    failure_reason='Prompt not found'
                )
                return None

            # Calculate version_baseline (children count = version index)
            children = await self.prompt_repo.get_children(action.artifact_id)
            version_baseline = len(children)

            # Build PromptModificationRequest
            request = PromptModificationRequest(
                prompt_id=action.artifact_id,
                finding_description=f"{finding.evidence} {finding.suggested_fix}",
                improvement_direction=action.improvement_description,
                preserve_sections=[]  # Let meta-prompt handle
            )

            # Call PromptEngineerService.modify_prompt()
            log.info(
                f"Calling PromptEngineerService.modify_prompt for prompt="
                f"{action.artifact_id[:8]}..."
            )
            new_prompt = await self.prompt_engineer.modify_prompt(
                request, improvement_attempt_id
            )

            # Calculate version_improvement (new child created)
            version_improvement = version_baseline + 1

            # Create A/B test
            log.info(
                f"Creating A/B test for improvement_attempt_id={improvement_attempt_id[:8]}..."
            )
            test = await self.ab_test_service.create_test(
                improvement_attempt_id=improvement_attempt_id,
                artifact_type="prompt",
                artifact_id=action.artifact_id,
                version_baseline=version_baseline,
                version_improvement=version_improvement,
                metric_weights=action.metric_weights
            )

            log.info(
                f"Created A/B test id={test.id} for prompt improvement"
            )

            return test.id

        except ValueError as e:
            # Test queued (active test already running)
            log.info(f"A/B test queued: {e}")
            return None

        except LLMError as e:
            log.warning(f"Prompt modification failed: {e}")
            await self.improvement_repo.update_status(
                improvement_attempt_id,
                status='failed',
                failure_reason=str(e)
            )
            return None

        except ValidationError as e:
            log.warning(f"Prompt modification validation failed: {e}")
            await self.improvement_repo.update_status(
                improvement_attempt_id,
                status='failed',
                failure_reason=str(e)
            )
            return None

        except Exception as e:
            log.error(f"Unexpected error in prompt improvement: {e}")
            await self.improvement_repo.update_status(
                improvement_attempt_id,
                status='failed',
                failure_reason=f"Unexpected: {str(e)}"
            )
            return None

    async def _execute_skill_improvement(
        self,
        action: ImprovementAction,
        finding: Finding,
        improvement_attempt_id: str,
    ) -> Optional[str]:
        """
        Execute skill improvement via ToolBuilderService and SandboxExecutorService.

        Flow:
        1. Fetch current skill
        2. Call ToolBuilderService.modify_tool()
        3. Check for duplicates via fingerprint
        4. Validate in sandbox via SandboxExecutorService.execute_tests()
        5. If tests pass, create A/B test
        6. If tests fail, mark attempt failed

        Args:
            action: ImprovementAction from Control Agent.
            finding: Original Finding being addressed.
            improvement_attempt_id: UUID of the improvement attempt record.

        Returns:
            A/B test ID if created, None if failed or queued.
        """
        try:
            # 1. Fetch current skill
            current_skill = await self.skill_repo.get_by_id(action.artifact_id)
            if not current_skill:
                log.error(f"Skill not found: id={action.artifact_id}")
                await self.improvement_repo.update_status(
                    improvement_attempt_id,
                    status='failed',
                    failure_reason='Skill not found'
                )
                return None

            # 2. Calculate version baseline
            children = await self.skill_repo.get_children(action.artifact_id)
            version_baseline = len(children)

            # 3. Build modification request and call ToolBuilderService
            request = ToolModificationRequest(
                skill_id=action.artifact_id,
                finding_description=f"{finding.evidence} {finding.suggested_fix}",
                improvement_direction=action.improvement_description,
            )

            log.info(
                f"Calling ToolBuilderService.modify_tool for skill="
                f"{action.artifact_id[:8]}..."
            )
            new_skill = await self.tool_builder.modify_tool(
                request, improvement_attempt_id
            )

            # 4. Check for duplicates via fingerprint
            fingerprint = new_skill.skill_metadata.get("code_fingerprint")
            if fingerprint:
                existing = await self.skill_repo.find_by_fingerprint(fingerprint)
                if existing and existing.id != new_skill.id:
                    log.warning(
                        f"Duplicate skill detected: fingerprint={fingerprint[:16]}..."
                    )
                    await self.improvement_repo.update_status(
                        improvement_attempt_id,
                        status='failed',
                        failure_reason='Duplicate skill already exists'
                    )
                    return None

            # 5. Execute tests in sandbox
            log.info(f"Executing tests in sandbox for skill={new_skill.id[:8]}...")

            # Build combined test code from test_cases
            test_code = self._build_test_file(new_skill)

            sandbox_result = await self.sandbox_executor.execute_tests(
                code=new_skill.code,
                test_code=test_code,
            )

            if not sandbox_result.success:
                log.warning(
                    f"Skill tests failed: passed={sandbox_result.tests_passed}, "
                    f"failed={sandbox_result.tests_failed}"
                )
                await self.improvement_repo.update_status(
                    improvement_attempt_id,
                    status='failed',
                    failure_reason=f"Tests failed: {sandbox_result.stderr or sandbox_result.stdout}"
                )
                return None

            log.info(f"Skill tests passed: {sandbox_result.tests_passed} tests")

            # 6. Create A/B test
            version_improvement = version_baseline + 1

            test = await self.ab_test_service.create_test(
                improvement_attempt_id=improvement_attempt_id,
                artifact_type="skill",
                artifact_id=action.artifact_id,
                version_baseline=version_baseline,
                version_improvement=version_improvement,
                metric_weights=action.metric_weights
            )

            log.info(f"Created A/B test id={test.id} for skill improvement")
            return test.id

        except ValueError as e:
            # Test queued or validation error
            log.info(f"Skill improvement queued or invalid: {e}")
            return None

        except LLMError as e:
            log.warning(f"Skill modification failed: {e}")
            await self.improvement_repo.update_status(
                improvement_attempt_id,
                status='failed',
                failure_reason=str(e)
            )
            return None

        except ValidationError as e:
            log.warning(f"Skill modification validation failed: {e}")
            await self.improvement_repo.update_status(
                improvement_attempt_id,
                status='failed',
                failure_reason=str(e)
            )
            return None

        except Exception as e:
            log.error(f"Unexpected error in skill improvement: {e}")
            await self.improvement_repo.update_status(
                improvement_attempt_id,
                status='failed',
                failure_reason=f"Unexpected: {str(e)}"
            )
            return None

    def _build_test_file(self, skill) -> str:
        """
        Build pytest test file from skill's test_cases.

        Args:
            skill: Skill with test_cases in skill_metadata or test_cases field.

        Returns:
            Combined test file content.
        """
        # Extract function name from skill (assume first def in code)
        match = re.search(r'def\s+(\w+)\s*\(', skill.code)
        func_name = match.group(1) if match else "unknown_function"

        lines = [
            "import pytest",
            f"from skill import {func_name}",
            "",
        ]

        for tc in skill.test_cases:
            if isinstance(tc, dict):
                lines.append(tc.get("test_code", ""))
            else:
                lines.append(tc.test_code)
            lines.append("")

        return "\n".join(lines)

    def _generate_fingerprint(self, finding: Finding) -> str:
        """
        Generate stable fingerprint for a finding.

        Uses SHA-256 hash of category + normalized suggested_fix to create
        a consistent identifier for the same type of finding across executions.

        This must match the exact implementation from ControlAgentService
        to ensure 3-strike tracking works correctly.

        Args:
            finding: Finding to generate fingerprint for.

        Returns:
            64-character hex string (SHA-256 hash).
        """
        # Normalize: lowercase and first 200 chars of suggested_fix
        normalized_fix = finding.suggested_fix[:200].lower().strip()
        content = f"{finding.category}:{normalized_fix}"

        return hashlib.sha256(content.encode()).hexdigest()
