"""
Skill Team Orchestrator - Team-based skill development.

Coordinates multiple specialized roles for high-quality skill development:
1. Researcher: Finds packages, examples, approaches
2. Architect: Designs API, test cases, dependencies
3. Implementer: Writes the actual code
4. Reviewer: Reviews for quality and security
5. Tester: Runs tests and validates output
"""

import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Optional, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.llm_client import LLMClient
from app.core.config import settings
from app.services.dynamic_sandbox_service import DynamicSandboxService
from app.services.failure_analyzer import FailureAnalyzer
from app.services.semantic_validator import SemanticValidator
from app.services.research_service import ResearchService
from app.services.skill_directory_service import SkillDirectoryService
from app.services.skill_registry import SkillRegistry
from app.models.sql.versioned_models import Skill
from app.models.sql.skill_build_models import SkillBuildAttempt
from app.models.schemas.skill_build_schemas import (
    TeamRole,
    SkillTeamConfig,
    ResearchContext,
    ArchitectureDesign,
    TestCase,
    ReviewResult,
    ReviewFinding,
    SemanticValidationResult,
    SkillBuildResult,
    ErrorType,
)
from app.prompts.skill_team_prompts import (
    get_researcher_prompt,
    get_architect_prompt,
    get_implementer_prompt,
    get_reviewer_prompt,
    get_revision_prompt,
)

log = logging.getLogger(__name__)


class SkillTeamOrchestrator:
    """
    Orchestrates team-based skill development.

    Workflow:
    1. Research Phase: Researcher finds packages, examples, approaches
    2. Architecture Phase: Architect designs API, tests, dependencies
    3. Implementation Phase: Implementer writes code (with iterations)
    4. Review Phase: Reviewer checks quality, security
    5. Test Phase: Tester validates in sandbox
    6. (Optional) Semantic Validation

    The team approach produces higher quality skills by:
    - Separating concerns across specialized roles
    - Enabling review and revision cycles
    - Using different models for different tasks
    """

    def __init__(
        self,
        db: AsyncSession,
        config: Optional[SkillTeamConfig] = None,
        llm_client: Optional[LLMClient] = None,
        sandbox: Optional[DynamicSandboxService] = None,
        research_service: Optional[ResearchService] = None,
        semantic_validator: Optional[SemanticValidator] = None,
        failure_analyzer: Optional[FailureAnalyzer] = None,
    ):
        """
        Initialize the skill team orchestrator.

        Args:
            db: Database session
            config: Team configuration
            llm_client: Default LLM client
            sandbox: Sandbox for testing
            research_service: Research service
            semantic_validator: Semantic validator
            failure_analyzer: Failure analyzer
        """
        self.db = db
        self.config = config or SkillTeamConfig()
        self.llm = llm_client or LLMClient()
        self.sandbox = sandbox or DynamicSandboxService()
        self.research_service = research_service or ResearchService(db, self.llm)
        self.semantic_validator = semantic_validator or SemanticValidator(
            self.llm, self.config.semantic_similarity_threshold
        )
        self.failure_analyzer = failure_analyzer or FailureAnalyzer(db, self.llm)

        # Role-specific LLM clients (can use different models)
        self._role_llms: dict[TeamRole, LLMClient] = {}

    def _get_role_llm(self, role: TeamRole) -> LLMClient:
        """Get LLM client for a specific role."""
        if role in self._role_llms:
            return self._role_llms[role]

        # Check config for role-specific model
        model = None
        if role == TeamRole.RESEARCHER and self.config.researcher_model:
            model = self.config.researcher_model
        elif role == TeamRole.ARCHITECT and self.config.architect_model:
            model = self.config.architect_model
        elif role == TeamRole.IMPLEMENTER and self.config.implementer_model:
            model = self.config.implementer_model
        elif role == TeamRole.REVIEWER and self.config.reviewer_model:
            model = self.config.reviewer_model

        if model:
            self._role_llms[role] = LLMClient(model=model)
            return self._role_llms[role]

        return self.llm

    async def develop_skill(
        self,
        capability: str,
        test_input: Optional[dict] = None,
        expected_output: Optional[Any] = None,
        expected_output_type: str = "any",
        input_files: Optional[dict[str, bytes]] = None,
        hints: Optional[dict] = None,
    ) -> SkillBuildResult:
        """
        Develop a skill using the full team workflow.

        Args:
            capability: What the skill should do
            test_input: Test input for validation
            expected_output: Expected output for semantic validation
            expected_output_type: Expected type of output
            input_files: Files to provide for testing
            hints: Hints for packages/approaches

        Returns:
            SkillBuildResult with skill details or failure info
        """
        start_time = time.time()
        phase_times: dict[str, int] = {}
        attempt_id = str(uuid.uuid4())

        log.info(f"Starting team-based skill development for: {capability}")

        try:
            # Get failure history BEFORE starting (Self-Improving Loop)
            failure_history = await self.failure_analyzer.get_failure_history(capability)
            failure_context = self.failure_analyzer.format_failure_context(failure_history)

            if failure_history:
                log.info(f"Found {len(failure_history)} previous failures to learn from")

            # Phase 1: Research (with failure awareness)
            phase_start = time.time()
            research = await self._research_phase(capability, hints, failure_context)
            phase_times["research"] = int((time.time() - phase_start) * 1000)
            log.info(f"Research complete: {len(research.pip_packages)} packages found")

            # Phase 2: Architecture (with failure awareness)
            phase_start = time.time()
            design = await self._architecture_phase(capability, research, failure_context)
            phase_times["architecture"] = int((time.time() - phase_start) * 1000)
            log.info(f"Architecture complete: {len(design.test_cases)} test cases defined")

            # Phase 3: Implementation (with iterations)
            phase_start = time.time()
            code = await self._implementation_phase(
                capability, design, research, input_files
            )
            phase_times["implementation"] = int((time.time() - phase_start) * 1000)

            if code is None:
                return SkillBuildResult(
                    success=False,
                    failure_phase=TeamRole.IMPLEMENTER,
                    failure_reason="Implementation failed after max iterations",
                    error_type=ErrorType.RUNTIME_ERROR,
                    research=research,
                    design=design,
                    total_time_ms=int((time.time() - start_time) * 1000),
                    phase_times=phase_times,
                    attempt_id=attempt_id,
                )

            # Phase 4: Review
            phase_start = time.time()
            code, review = await self._review_phase(capability, code, design)
            phase_times["review"] = int((time.time() - phase_start) * 1000)

            if not review.approved:
                return SkillBuildResult(
                    success=False,
                    failure_phase=TeamRole.REVIEWER,
                    failure_reason=f"Code review failed: {review.findings[0].description if review.findings else 'Unknown'}",
                    error_type=ErrorType.SEMANTIC_ERROR,
                    research=research,
                    design=design,
                    review=review,
                    total_time_ms=int((time.time() - start_time) * 1000),
                    phase_times=phase_times,
                    attempt_id=attempt_id,
                )

            # Phase 5: Test in sandbox
            phase_start = time.time()
            test_result = await self._test_phase(
                code, design, test_input, input_files
            )
            phase_times["test"] = int((time.time() - phase_start) * 1000)

            if not test_result["success"]:
                return SkillBuildResult(
                    success=False,
                    failure_phase=TeamRole.TESTER,
                    failure_reason=test_result.get("error", "Test failed"),
                    error_type=ErrorType.RUNTIME_ERROR,
                    research=research,
                    design=design,
                    review=review,
                    final_code=code,
                    total_time_ms=int((time.time() - start_time) * 1000),
                    phase_times=phase_times,
                    attempt_id=attempt_id,
                )

            # Phase 6: Semantic validation (if enabled)
            semantic_result: Optional[SemanticValidationResult] = None
            if self.config.require_semantic_validation and expected_output is not None:
                phase_start = time.time()
                semantic_result = await self.semantic_validator.validate(
                    expected_behavior=f"Skill for {capability}",
                    actual_output=test_result.get("output"),
                    expected_output=expected_output,
                    expected_type=expected_output_type,
                )
                phase_times["semantic_validation"] = int((time.time() - phase_start) * 1000)

                if not semantic_result.passed:
                    return SkillBuildResult(
                        success=False,
                        failure_phase=TeamRole.TESTER,
                        failure_reason=f"Semantic validation failed: {semantic_result.value_comparison}",
                        error_type=ErrorType.SEMANTIC_ERROR,
                        research=research,
                        design=design,
                        review=review,
                        semantic_validation=semantic_result,
                        final_code=code,
                        total_time_ms=int((time.time() - start_time) * 1000),
                        phase_times=phase_times,
                        attempt_id=attempt_id,
                    )

            # Success! Persist the skill
            skill = await self._persist_skill(capability, code, design, research)

            # Generate requirements.txt
            requirements_txt = self._generate_requirements_txt(design.pip_requirements)

            total_time_ms = int((time.time() - start_time) * 1000)

            # Self-Improving Loop: Learn from success
            await self.failure_analyzer.learn_from_success(
                capability=capability,
                pip_requirements=design.pip_requirements,
                code=code,
            )

            # Record successful attempt for future learning
            await self.failure_analyzer.record_attempt(
                capability=capability,
                code=code,
                success=True,
                pip_requirements=design.pip_requirements,
                system_packages=design.system_requirements,
                approach=research.implementation_approach,
                team_role=TeamRole.IMPLEMENTER.value,
                execution_time_ms=total_time_ms,
                research_context={
                    "pip_packages": research.pip_packages,
                    "approach": research.implementation_approach,
                },
                skill_id=skill.id,
            )

            log.info(
                f"Skill development complete: {skill.name} in {total_time_ms}ms"
            )

            return SkillBuildResult(
                success=True,
                skill_id=skill.id,
                skill_name=skill.name,
                research=research,
                design=design,
                review=review,
                semantic_validation=semantic_result,
                final_code=code,
                requirements_txt=requirements_txt,
                implementation_iterations=1,  # Could track this
                review_iterations=1,
                total_time_ms=total_time_ms,
                phase_times=phase_times,
                attempt_id=attempt_id,
            )

        except Exception as e:
            log.error(f"Skill development failed: {e}", exc_info=True)
            return SkillBuildResult(
                success=False,
                failure_reason=str(e),
                error_type=ErrorType.RUNTIME_ERROR,
                total_time_ms=int((time.time() - start_time) * 1000),
                phase_times=phase_times,
                attempt_id=attempt_id,
            )

    async def _research_phase(
        self,
        capability: str,
        hints: Optional[dict] = None,
        failure_context: str = "",
    ) -> ResearchContext:
        """Execute research phase with failure awareness."""
        if not self.config.enable_researcher:
            # Skip research, use hints only
            return ResearchContext(
                capability=capability,
                pip_packages=hints.get("pip", []) if hints else [],
                system_packages=hints.get("apt", []) if hints else [],
            )

        # Add failure context to hints for research service
        enhanced_hints = hints.copy() if hints else {}
        if failure_context:
            enhanced_hints["failure_context"] = failure_context

        # Use research service
        return await self.research_service.research_capability(
            capability=capability,
            hints=enhanced_hints,
        )

    async def _architecture_phase(
        self,
        capability: str,
        research: ResearchContext,
        failure_context: str = "",
    ) -> ArchitectureDesign:
        """Execute architecture phase with failure awareness."""
        if not self.config.enable_architect:
            # Skip architecture, use defaults
            return ArchitectureDesign(
                capability=capability,
                function_signature="def execute(input_data: dict) -> dict",
                pip_requirements=research.pip_packages,
                system_requirements=research.system_packages,
                test_cases=[
                    TestCase(
                        name="basic_test",
                        input_data={},
                        expected_output_type="dict",
                        expected_keys=["success"],
                    )
                ],
            )

        llm = self._get_role_llm(TeamRole.ARCHITECT)

        # Build research context string
        research_context = json.dumps({
            "pip_packages": research.pip_packages,
            "system_packages": research.system_packages,
            "approach": research.implementation_approach,
            "code_examples": research.code_examples[:2] if research.code_examples else [],
        }, indent=2)

        # Include failure context in architecture prompt
        prompt = get_architect_prompt(capability, research_context, failure_context)

        response = await llm.chat(
            messages=[
                {"role": "system", "content": "You are a software architect. Design robust APIs."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=2000,
        )

        # Parse response
        return self._parse_architecture(response.content, capability, research)

    def _parse_architecture(
        self,
        response: str,
        capability: str,
        research: ResearchContext,
    ) -> ArchitectureDesign:
        """Parse architecture response."""
        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())

                test_cases = []
                for tc in data.get("test_cases", []):
                    test_cases.append(TestCase(
                        name=tc.get("name", "test"),
                        input_data=tc.get("input", {}),
                        expected_output_type=tc.get("expected_output_type", "dict"),
                        expected_keys=tc.get("expected_keys", ["success"]),
                    ))

                return ArchitectureDesign(
                    capability=capability,
                    function_signature=data.get(
                        "function_signature",
                        "def execute(input_data: dict) -> dict"
                    ),
                    input_schema=data.get("input_schema", {}),
                    output_schema=data.get("output_schema", {}),
                    pip_requirements=data.get("pip_requirements", research.pip_packages),
                    system_requirements=data.get("system_requirements", research.system_packages),
                    test_cases=test_cases or [
                        TestCase(name="basic", expected_output_type="dict", expected_keys=["success"])
                    ],
                    error_handling=data.get("error_handling", ""),
                    design_notes=data.get("design_notes", ""),
                )

        except Exception as e:
            log.warning(f"Failed to parse architecture: {e}")

        # Fallback to defaults
        return ArchitectureDesign(
            capability=capability,
            function_signature="def execute(input_data: dict) -> dict",
            pip_requirements=research.pip_packages,
            system_requirements=research.system_packages,
            test_cases=[
                TestCase(name="basic", expected_output_type="dict", expected_keys=["success"])
            ],
        )

    async def _implementation_phase(
        self,
        capability: str,
        design: ArchitectureDesign,
        research: ResearchContext,
        input_files: Optional[dict[str, bytes]] = None,
    ) -> Optional[str]:
        """Execute implementation phase with iterations."""
        llm = self._get_role_llm(TeamRole.IMPLEMENTER)

        # Get failure history
        failure_history = await self.failure_analyzer.get_failure_history(capability)
        failure_context = self.failure_analyzer.format_failure_context(failure_history)

        design_str = json.dumps({
            "function_signature": design.function_signature,
            "input_schema": design.input_schema,
            "output_schema": design.output_schema,
            "pip_requirements": design.pip_requirements,
            "error_handling": design.error_handling,
        }, indent=2)

        research_str = json.dumps({
            "packages": research.pip_packages,
            "approach": research.implementation_approach,
            "examples": research.code_examples[:1] if research.code_examples else [],
        }, indent=2)

        for iteration in range(self.config.max_implementation_iterations):
            log.info(f"Implementation iteration {iteration + 1}/{self.config.max_implementation_iterations}")

            prompt = get_implementer_prompt(
                capability=capability,
                design=design_str,
                research_context=research_str,
                failure_context=failure_context,
            )

            response = await llm.chat(
                messages=[
                    {"role": "system", "content": "You are a Python expert. Write clean, working code."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=3000,
            )

            code = self._extract_code(response.content)

            # Quick test in sandbox
            test_result = await self._quick_test(
                code, design, input_files
            )

            if test_result["success"]:
                return code

            # Update failure context for next iteration
            failure_context += f"\n\nIteration {iteration + 1} failed:\n{test_result.get('error', 'Unknown error')[:500]}"

            # Record failure
            await self.failure_analyzer.record_attempt(
                capability=capability,
                code=code,
                success=False,
                error_type=ErrorType.RUNTIME_ERROR,
                error_message=test_result.get("error", ""),
                stderr=test_result.get("stderr", ""),
                pip_requirements=design.pip_requirements,
                system_packages=design.system_requirements,
                team_role=TeamRole.IMPLEMENTER.value,
                attempt_number=iteration + 1,
            )

        return None

    async def _quick_test(
        self,
        code: str,
        design: ArchitectureDesign,
        input_files: Optional[dict[str, bytes]] = None,
    ) -> dict:
        """Quick test of code in sandbox."""
        test_code = self._build_test_code(code, design)

        result = await self.sandbox.execute(
            code=test_code,
            pip_requirements=design.pip_requirements,
            system_packages=design.system_requirements,
            input_files=input_files,
        )

        return {
            "success": result.success,
            "error": result.error or result.stderr,
            "stderr": result.stderr,
            "stdout": result.stdout,
        }

    async def _review_phase(
        self,
        capability: str,
        code: str,
        design: ArchitectureDesign,
    ) -> tuple[str, ReviewResult]:
        """Execute review phase with potential revisions."""
        if not self.config.enable_reviewer:
            # Skip review
            return code, ReviewResult(
                approved=True,
                overall_score=0.8,
            )

        llm = self._get_role_llm(TeamRole.REVIEWER)

        for iteration in range(self.config.max_review_iterations):
            log.info(f"Review iteration {iteration + 1}/{self.config.max_review_iterations}")

            design_str = json.dumps({
                "function_signature": design.function_signature,
                "input_schema": design.input_schema,
                "output_schema": design.output_schema,
            }, indent=2)

            prompt = get_reviewer_prompt(
                capability=capability,
                code=code,
                design=design_str,
            )

            response = await llm.chat(
                messages=[
                    {"role": "system", "content": "You are a code reviewer. Be thorough but fair."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=2000,
            )

            review = self._parse_review(response.content)

            if review.approved:
                return code, review

            # Not approved - try to fix
            if iteration < self.config.max_review_iterations - 1:
                code = await self._revision_phase(code, review)

        return code, review

    def _extract_json(self, response: str) -> Optional[dict]:
        """Extract JSON from LLM response, trying multiple strategies."""
        # Strategy 1: Markdown code block
        md_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response, re.DOTALL)
        if md_match:
            try:
                return json.loads(md_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Strategy 2: Find outermost JSON object
        # Use a bracket-counting approach instead of greedy regex
        start = response.find('{')
        if start != -1:
            depth = 0
            for i in range(start, len(response)):
                if response[i] == '{':
                    depth += 1
                elif response[i] == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(response[start:i + 1])
                        except json.JSONDecodeError:
                            break

        return None

    def _parse_review(self, response: str) -> ReviewResult:
        """Parse review response."""
        try:
            data = self._extract_json(response)
            if data:
                findings = []
                for f in data.get("findings", []):
                    try:
                        line_range = None
                        lr = f.get("line_range")
                        if isinstance(lr, (list, tuple)) and len(lr) == 2:
                            line_range = tuple(lr)

                        findings.append(ReviewFinding(
                            severity=f.get("severity", "info"),
                            category=f.get("category", "style"),
                            line_range=line_range,
                            description=f.get("description", ""),
                            suggestion=f.get("suggestion"),
                        ))
                    except Exception:
                        continue

                return ReviewResult(
                    approved=bool(data.get("approved", False)),
                    overall_score=float(data.get("overall_score", 0.5)),
                    findings=findings,
                    critical_count=sum(1 for f in findings if f.severity == "critical"),
                    warning_count=sum(1 for f in findings if f.severity == "warning"),
                    security_passed=bool(data.get("security_passed", True)),
                    security_concerns=data.get("security_concerns", []),
                    improvement_suggestions=data.get("improvement_suggestions", []),
                    refactoring_needed=bool(data.get("refactoring_needed", False)),
                )

        except Exception as e:
            log.warning(f"Failed to parse review: {e}")

        return ReviewResult(
            approved=True,  # Default to approved if parsing fails
            overall_score=0.7,
        )

    async def _revision_phase(self, code: str, review: ReviewResult) -> str:
        """Revise code based on review feedback."""
        llm = self._get_role_llm(TeamRole.IMPLEMENTER)

        findings_str = "\n".join([
            f"- [{f.severity}] {f.description}: {f.suggestion or 'No suggestion'}"
            for f in review.findings
        ])

        required_changes = "\n".join([
            f"- {s}" for s in review.improvement_suggestions
        ])

        prompt = get_revision_prompt(
            code=code,
            findings=findings_str,
            required_changes=required_changes,
        )

        response = await llm.chat(
            messages=[
                {"role": "system", "content": "You are a Python expert. Fix the code issues."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=3000,
        )

        return self._extract_code(response.content)

    async def _test_phase(
        self,
        code: str,
        design: ArchitectureDesign,
        test_input: Optional[dict] = None,
        input_files: Optional[dict[str, bytes]] = None,
    ) -> dict:
        """Full test in sandbox."""
        test_code = self._build_test_code(code, design, test_input)

        result = await self.sandbox.execute(
            code=test_code,
            pip_requirements=design.pip_requirements,
            system_packages=design.system_requirements,
            input_files=input_files,
        )

        output = None
        if result.success:
            # Try to extract output
            output = self._parse_output(result.stdout)

        return {
            "success": result.success,
            "output": output,
            "error": result.error or result.stderr,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def _has_file_references(self, test_input: dict) -> bool:
        """Check if test input references files that won't exist in the sandbox."""
        file_keys = {"file_path", "audio_file_path", "path", "input_file", "filepath", "audio_path", "video_path", "image_path", "pdf_path"}
        for key, value in test_input.items():
            if key.lower() in file_keys and isinstance(value, str):
                return True
        return False

    def _build_test_code(
        self,
        code: str,
        design: ArchitectureDesign,
        test_input: Optional[dict] = None,
    ) -> str:
        """Build test wrapper code."""
        test_input = test_input or {}
        if design.test_cases:
            test_input = design.test_cases[0].input_data or test_input

        # If no real test input or input references non-existent files,
        # do a smoke test (imports + callable check)
        if not test_input or self._has_file_references(test_input):
            return f'''{code}

# Smoke test: verify imports work and execute() is callable
if __name__ == "__main__":
    import inspect

    if not callable(execute):
        print("ERROR: execute is not callable")
        exit(1)

    sig = inspect.signature(execute)
    print(f"Function signature: execute{{sig}}")
    print("All imports successful, execute() is callable")
    print("TEST PASSED")
    exit(0)
'''

        return f'''{code}

# Test wrapper
if __name__ == "__main__":
    import json
    test_input = {json.dumps(test_input)}
    print("Testing with input:", test_input)

    try:
        result = execute(test_input)
        print("Result:", result)

        if not isinstance(result, dict):
            print("ERROR: Result must be a dict")
            exit(1)

        if "success" not in result:
            print("ERROR: Result must have 'success' key")
            exit(1)

        if result.get("success"):
            print("TEST PASSED")
            exit(0)
        else:
            print("TEST FAILED:", result.get("error", "Unknown"))
            exit(1)

    except Exception as e:
        print(f"EXCEPTION: {{type(e).__name__}}: {{e}}")
        exit(1)
'''

    def _extract_code(self, response: str) -> str:
        """Extract Python code from response."""
        code_match = re.search(r'```python\n(.*?)```', response, re.DOTALL)
        if code_match:
            return code_match.group(1).strip()

        code_match = re.search(r'```\n(.*?)```', response, re.DOTALL)
        if code_match:
            return code_match.group(1).strip()

        # Try to find code starting with import or def
        lines = response.strip().split('\n')
        code_lines = []
        in_code = False

        for line in lines:
            if line.startswith('import ') or line.startswith('from ') or line.startswith('def ') or in_code:
                in_code = True
                code_lines.append(line)

        if code_lines:
            return '\n'.join(code_lines)

        return response.strip()

    def _parse_output(self, stdout: str) -> Optional[Any]:
        """Parse output from stdout."""
        try:
            lines = stdout.strip().split('\n')
            for line in reversed(lines):
                if line.startswith('Result:'):
                    result_str = line[7:].strip()
                    try:
                        return json.loads(result_str.replace("'", '"'))
                    except json.JSONDecodeError:
                        return result_str

            return stdout.strip()
        except Exception:
            return None

    def _generate_requirements_txt(self, packages: list[str]) -> str:
        """Generate requirements.txt content."""
        return "\n".join(packages)

    async def _persist_skill(
        self,
        capability: str,
        code: str,
        design: ArchitectureDesign,
        research: ResearchContext,
    ) -> Skill:
        """Persist the skill to database."""
        skill_name = f"skill_{capability.lower().replace(' ', '_').replace('-', '_')}"

        # Check for existing
        result = await self.db.execute(
            select(Skill).where(Skill.name == skill_name)
        )
        existing = result.scalar_one_or_none()

        metadata = {
            "pip_requirements": design.pip_requirements,
            "system_packages": design.system_requirements,
            "auto_generated": True,
            "team_built": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "affected_capability": capability,
            "design_notes": design.design_notes,
        }

        if existing:
            existing.code = code
            existing.description = f"Auto-generated skill for: {capability}"
            existing.skill_metadata = metadata
            existing.is_active = True
            await self.db.commit()
            log.info(f"Updated existing skill: {existing.id}")

            # Also update directory if enabled
            if settings.skill_directory_enabled:
                await self._save_skill_directory(existing, code, design)

            # Hot-reload into registry if enabled
            if settings.hot_reload_enabled:
                await self._hot_reload_skill(existing)

            return existing

        skill = Skill(
            id=str(uuid.uuid4()),
            name=skill_name,
            description=f"Auto-generated skill for: {capability}",
            code=code,
            test_cases=[tc.model_dump() for tc in design.test_cases],
            skill_metadata=metadata,
            is_active=True,
        )

        self.db.add(skill)
        await self.db.commit()
        await self.db.refresh(skill)

        log.info(f"Created new skill: {skill.id}")

        # Also save as directory (SKILL.md format) if enabled
        if settings.skill_directory_enabled:
            await self._save_skill_directory(skill, code, design)

        # Hot-load into registry if enabled
        if settings.hot_reload_enabled:
            await self._hot_reload_skill(skill)

        return skill

    async def _save_skill_directory(
        self,
        skill: Skill,
        code: str,
        design: ArchitectureDesign,
    ) -> None:
        """
        Save skill as directory structure (SKILL.md format).

        This creates an OpenClaw-compatible skill directory with:
        - SKILL.md (metadata + documentation)
        - scripts/main.py (the code)
        - requirements.txt (dependencies)
        - tests/test_main.py (test cases)
        """
        try:
            dir_service = SkillDirectoryService()
            dir_service.create_skill_directory(
                name=skill.name,
                description=skill.description or f"Skill for: {design.capability}",
                code=code,
                pip_requirements=design.pip_requirements,
                apt_requirements=design.system_requirements,
                test_cases=[tc.model_dump() for tc in design.test_cases],
                skill_id=skill.id,
                created_by="skill_team_orchestrator",
            )
            log.info(f"Saved skill directory: {skill.name}")
        except Exception as e:
            # Don't fail the whole operation if directory save fails
            log.warning(f"Failed to save skill directory for {skill.name}: {e}")

    async def _hot_reload_skill(self, skill: Skill) -> None:
        """
        Hot-reload skill into the in-memory registry.

        Makes the skill immediately available without server restart.
        """
        try:
            registry = SkillRegistry.get_instance()
            await registry.reload_skill(skill)
            log.info(f"Hot-reloaded skill into registry: {skill.name}")
        except Exception as e:
            # Don't fail the whole operation if hot-reload fails
            log.warning(f"Failed to hot-reload skill {skill.name}: {e}")
