"""
Autonomous Skill Builder - Self-improving agent that develops skills through research and iteration.

This service implements an OpenClaw-style skill development flow:
1. Research: Search the web for solutions to capability gaps
2. Generate: Create code based on research findings
3. Test: Execute code in sandbox with required dependencies
4. Iterate: Fix errors based on feedback (max N attempts)
5. Persist: Save successful skills with metadata

The system improves itself by:
- Learning which packages solve which problems
- Caching successful dependency combinations
- Building a knowledge base of working code patterns
"""

import asyncio
import ast
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Any

from sqlalchemy import select

from app.core.llm_client import LLMClient
from app.skills.testing.docker_sandbox import DynamicSandboxService, SandboxResult
from app.feedback_loop.analysis.failure_analyzer import FailureAnalyzer, FailureAnalysis
from app.skills.testing.package_resolver import PackageResolver
from app.skills.testing.semantic_validator import SemanticValidator
from app.models.sql.versioned_models import Skill
from app.models.schemas.skill_build_schemas import ErrorType, SemanticValidationResult
from pydantic import BaseModel
from typing import Literal

log = logging.getLogger(__name__)


# -- Pydantic models for LLM-based interface derivation --

class PropertySchema(BaseModel):
    """Schema for a single skill parameter."""
    type: Literal["string", "integer", "number", "boolean", "object", "array", "file"]
    description: str = ""

class InterfaceInput(BaseModel):
    """Input schema of a skill."""
    type: str = "object"
    properties: dict[str, PropertySchema]
    required: list[str]

class SkillInterfaceOutput(BaseModel):
    """Structured LLM response: only the interface schema."""
    input: InterfaceInput


@dataclass
class ResearchResult:
    """Result of web research for a capability."""
    query: str
    sources: list[str] = field(default_factory=list)
    code_examples: list[str] = field(default_factory=list)
    recommended_packages: list[str] = field(default_factory=list)
    recommended_system_packages: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class SkillDraft:
    """Draft of a skill before testing."""
    name: str
    description: str
    code: str
    pip_requirements: list[str] = field(default_factory=list)
    system_packages: list[str] = field(default_factory=list)
    function_name: str = "execute"
    interface: dict = field(default_factory=dict)


@dataclass
class SkillBuildResult:
    """Result of autonomous skill building."""
    success: bool
    skill: Optional[Skill] = None
    skill_id: Optional[str] = None
    iterations: int = 0
    research_sources: list[str] = field(default_factory=list)
    final_error: Optional[str] = None
    execution_time_ms: int = 0


# Import shared package hints — single source of truth in research_service
from app.skills.building.research import CAPABILITY_PACKAGE_HINTS


class AutonomousSkillBuilder:
    """
    Builds skills autonomously through research, code generation, and iterative testing.

    This is the core of the self-improving system. When a capability gap is detected,
    this service:
    1. Researches how to implement the capability
    2. Generates code based on research
    3. Tests the code in a sandbox
    4. Iterates on failures
    5. Persists successful skills

    Example:
        builder = AutonomousSkillBuilder(db_session)
        result = await builder.build_skill(
            capability="audio transcription",
            test_input={"file_path": "/workspace/test.opus"},
            expected_output_type="str",
        )
        if result.success:
            print(f"Skill created: {result.skill_id}")
    """

    MAX_ITERATIONS = 10
    MAX_RESEARCH_RESULTS = 5

    def __init__(
        self,
        session_factory,
        llm_client: Optional[LLMClient] = None,
        sandbox: Optional[DynamicSandboxService] = None,
        failure_analyzer: Optional[FailureAnalyzer] = None,
        package_resolver: Optional[PackageResolver] = None,
        semantic_validator: Optional[SemanticValidator] = None,
        enable_semantic_validation: bool = True,
        semantic_threshold: float = 0.7,
    ):
        """
        Initialize the autonomous skill builder.

        Args:
            db: Database session for persisting skills.
            llm_client: LLM client for code generation (uses default if not provided).
            sandbox: Sandbox service for testing (creates new if not provided).
            failure_analyzer: Failure analyzer for learning from errors.
            package_resolver: Package resolver for import->pip resolution.
            semantic_validator: Semantic validator for output validation.
            enable_semantic_validation: Whether to perform semantic validation.
            semantic_threshold: Minimum similarity score for semantic validation.
        """
        self.session_factory = session_factory
        self.llm = llm_client or LLMClient()
        self._code_gen_llm: Optional[LLMClient] = None
        self.sandbox = sandbox or DynamicSandboxService()
        self.failure_analyzer = failure_analyzer or FailureAnalyzer(session_factory, self.llm)
        self.package_resolver = package_resolver
        self.semantic_validator = semantic_validator or SemanticValidator(
            self.llm, semantic_threshold
        )
        self.enable_semantic_validation = enable_semantic_validation
        self.semantic_threshold = semantic_threshold

    def _get_code_gen_llm(self) -> LLMClient:
        """LLM-Client für Code-Generierung (nutzt stärkeres Modell aus Config)."""
        if self._code_gen_llm is None:
            from app.core.config import settings
            model = settings.skill_implementer_model
            if model:
                self._code_gen_llm = LLMClient(model=model)
            else:
                self._code_gen_llm = self.llm
        return self._code_gen_llm

    async def build_skill(
        self,
        capability: str,
        test_input: Optional[dict] = None,
        expected_output_type: str = "any",
        expected_output: Optional[Any] = None,
        expected_keys: Optional[list[str]] = None,
        input_files: Optional[dict[str, bytes]] = None,
        hints: Optional[dict] = None,
    ) -> SkillBuildResult:
        """
        Build a skill for the given capability autonomously.

        Args:
            capability: Description of the capability needed (e.g., "audio transcription").
            test_input: Optional test input dict to validate the skill.
            expected_output_type: Expected type of output ("str", "dict", "list", "any").
            input_files: Optional files to provide for testing.
            hints: Optional hints about packages or approaches to try.

        Returns:
            SkillBuildResult with success status and skill details.
        """
        start_time = datetime.now(timezone.utc)
        log.info(f"Starting autonomous skill build for: {capability}")

        # Step 0: Get failure history to avoid repeating mistakes
        failure_history = await self.failure_analyzer.get_failure_history(capability)
        failure_context = self.failure_analyzer.format_failure_context(failure_history)
        if failure_history:
            log.info(f"Found {len(failure_history)} previous failed attempts")

        # Step 1: Research
        research = await self._research_capability(capability, hints)
        log.info(f"Research complete: {len(research.code_examples)} examples, "
                 f"packages: {research.recommended_packages}")

        # Step 2: Generate initial code (include failure context)
        draft = await self._generate_skill_code(capability, research, failure_context)
        log.info(f"Generated skill draft: {draft.name}, "
                 f"pip: {draft.pip_requirements}, apt: {draft.system_packages}")

        # Step 3: Iterative testing with session reuse
        last_error = None
        last_analysis: Optional[FailureAnalysis] = None
        iteration_errors: list[dict] = []  # Accumulated errors for approach-switching
        iteration = 0

        while iteration < self.MAX_ITERATIONS:
            # Open a session for the current package requirements
            current_pip = list(draft.pip_requirements)
            current_apt = list(draft.system_packages)

            async with self.sandbox.session(
                pip_requirements=current_pip,
                system_packages=current_apt,
                input_files=input_files,
            ) as session:
                while iteration < self.MAX_ITERATIONS:
                    log.info(f"Testing iteration {iteration + 1}/{self.MAX_ITERATIONS}")

                    # Build test code
                    test_code = self._build_test_code(draft, test_input, expected_output_type)

                    # Execute in session (reuses container)
                    result = await session.execute_code(
                        code=f"{draft.code}\n\n{test_code}",
                    )

                    execution_time_ms = int(
                        (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
                    )

                    if result.success:
                        log.info(f"Skill test passed on iteration {iteration + 1}")

                        # Step 3.5: Semantic validation (if enabled)
                        semantic_result: Optional[SemanticValidationResult] = None
                        if self.enable_semantic_validation:
                            log.info("Running semantic validation...")
                            try:
                                # Parse output from stdout
                                skill_output = self._parse_skill_output(result.stdout)

                                semantic_result = await self.semantic_validator.validate(
                                    expected_behavior=f"Skill for {capability}",
                                    actual_output=skill_output,
                                    expected_output=expected_output,
                                    expected_type=expected_output_type,
                                    expected_keys=expected_keys,
                                )

                                if not semantic_result.passed:
                                    log.warning(
                                        f"Semantic validation failed: score={semantic_result.similarity_score:.2f}, "
                                        f"reason={semantic_result.value_comparison}"
                                    )
                                    # Treat as failure and continue iteration
                                    last_error = f"Semantic validation failed: {semantic_result.value_comparison}"
                                    last_analysis = await self.failure_analyzer.analyze_failure(
                                        capability=capability,
                                        code=draft.code,
                                        error_message=last_error,
                                        stderr="",
                                        pip_requirements=draft.pip_requirements,
                                    )
                                    # Override error type to semantic
                                    last_analysis.error_type = ErrorType.SEMANTIC_ERROR

                                    # Record semantic failure
                                    await self.failure_analyzer.record_attempt(
                                        capability=capability,
                                        code=draft.code,
                                        success=False,
                                        error_type=ErrorType.SEMANTIC_ERROR,
                                        error_message=last_error,
                                        stdout=result.stdout,
                                        pip_requirements=draft.pip_requirements,
                                        system_packages=draft.system_packages,
                                        approach="direct" if iteration == 0 else "iterative",
                                        attempt_number=iteration + 1,
                                        execution_time_ms=execution_time_ms,
                                        failure_analysis={
                                            "error_type": "semantic_error",
                                            "root_cause": semantic_result.value_comparison,
                                            "similarity_score": semantic_result.similarity_score,
                                        },
                                    )

                                    if iteration < self.MAX_ITERATIONS - 1:
                                        draft = await self._fix_skill_code(
                                            draft, last_error, research, last_analysis, iteration_errors
                                        )
                                        iteration += 1
                                        # Check if requirements changed
                                        if set(draft.pip_requirements) != set(current_pip) or set(draft.system_packages) != set(current_apt):
                                            log.info("Requirements changed after fix, restarting session")
                                            break
                                    continue  # Try next iteration

                                log.info(f"Semantic validation passed: score={semantic_result.similarity_score:.2f}")

                            except Exception as e:
                                log.warning(f"Semantic validation error: {e}")
                                # Don't fail the build on validation errors, just log

                        # Record successful attempt
                        attempt_id = await self.failure_analyzer.record_attempt(
                            capability=capability,
                            code=draft.code,
                            success=True,
                            pip_requirements=draft.pip_requirements,
                            system_packages=draft.system_packages,
                            approach="direct" if iteration == 0 else "iterative",
                            attempt_number=iteration + 1,
                            execution_time_ms=execution_time_ms,
                            research_context={
                                "packages": research.recommended_packages,
                                "sources": research.sources,
                            },
                        )

                        # Learn from success
                        await self.failure_analyzer.learn_from_success(
                            capability=capability,
                            pip_requirements=draft.pip_requirements,
                            code=draft.code,
                        )

                        # Step 4: Persist skill
                        skill = await self._persist_skill(draft, research, iteration + 1)

                        return SkillBuildResult(
                            success=True,
                            skill=skill,
                            skill_id=skill.id,
                            iterations=iteration + 1,
                            research_sources=research.sources,
                            execution_time_ms=execution_time_ms,
                        )

                    # Test failed - analyze and try to fix
                    last_error = result.error or result.stderr
                    log.warning(f"Iteration {iteration + 1} failed: {last_error[:200]}")

                    # Detect which libraries are being used for approach-switching
                    used_libs = self._detect_libraries(draft.code)

                    # Accumulate error for approach-switching logic
                    iteration_errors.append({
                        "iteration": iteration + 1,
                        "error": last_error[:300],
                        "libraries": used_libs,
                    })

                    # Analyze the failure
                    last_analysis = await self.failure_analyzer.analyze_failure(
                        capability=capability,
                        code=draft.code,
                        error_message=last_error,
                        stderr=result.stderr,
                        pip_requirements=draft.pip_requirements,
                    )

                    # Record failed attempt
                    await self.failure_analyzer.record_attempt(
                        capability=capability,
                        code=draft.code,
                        success=False,
                        error_type=last_analysis.error_type,
                        error_message=last_error,
                        stderr=result.stderr,
                        stdout=result.stdout,
                        pip_requirements=draft.pip_requirements,
                        system_packages=draft.system_packages,
                        approach="direct" if iteration == 0 else "iterative",
                        attempt_number=iteration + 1,
                        execution_time_ms=execution_time_ms,
                        failure_analysis={
                            "error_type": last_analysis.error_type.value,
                            "root_cause": last_analysis.root_cause,
                            "suggested_fixes": last_analysis.suggested_fixes,
                            "alternative_packages": last_analysis.alternative_packages,
                        },
                    )

                    iteration += 1
                    if iteration < self.MAX_ITERATIONS:
                        # Try to fix the code using analysis + accumulated errors
                        draft = await self._fix_skill_code(
                            draft, last_error, research, last_analysis, iteration_errors
                        )
                        # Check if requirements changed — need a new session
                        if set(draft.pip_requirements) != set(current_pip) or set(draft.system_packages) != set(current_apt):
                            log.info("Requirements changed after fix, restarting session")
                            break

        # All iterations failed
        execution_time_ms = int(
            (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        )

        log.error(f"Skill build failed after {self.MAX_ITERATIONS} iterations")

        return SkillBuildResult(
            success=False,
            iterations=self.MAX_ITERATIONS,
            research_sources=research.sources,
            final_error=last_error,
            execution_time_ms=execution_time_ms,
        )

    async def _research_capability(
        self,
        capability: str,
        hints: Optional[dict] = None,
    ) -> ResearchResult:
        """Research how to implement a capability using web search."""
        log.info(f"Researching capability: {capability}")

        # Check for known package hints first
        capability_lower = capability.lower()
        known_hints = CAPABILITY_PACKAGE_HINTS.get(capability_lower, {})

        result = ResearchResult(query=capability)

        # Add known hints
        if known_hints:
            result.recommended_packages = known_hints.get("pip", [])[:3]
            result.recommended_system_packages = known_hints.get("apt", [])

        # Add user hints
        if hints:
            if hints.get("pip"):
                result.recommended_packages.extend(hints["pip"])
            if hints.get("apt"):
                result.recommended_system_packages.extend(hints["apt"])

        # Web search for more information
        try:
            search_query = f"python {capability} implementation example code 2024"

            # Use LLM to search and summarize
            search_prompt = f"""Search for how to implement "{capability}" in Python.

Find:
1. Which pip packages are commonly used
2. Any system dependencies (apt packages) needed
3. Code examples showing the implementation

Return a JSON object with:
{{
    "packages": ["package1", "package2"],
    "system_packages": ["apt-package1"],
    "code_example": "# example code here",
    "summary": "Brief description of the approach"
}}"""

            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": "You are a Python expert. Provide practical implementation advice."},
                    {"role": "user", "content": search_prompt},
                ],
                temperature=0.3,
            )

            # Try to parse response as JSON
            try:
                # Extract JSON from response
                content = response.content
                json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                    if data.get("packages"):
                        result.recommended_packages.extend(data["packages"])
                    if data.get("system_packages"):
                        result.recommended_system_packages.extend(data["system_packages"])
                    if data.get("code_example"):
                        result.code_examples.append(data["code_example"])
                    if data.get("summary"):
                        result.summary = data["summary"]
            except json.JSONDecodeError:
                log.warning("Could not parse research response as JSON")
                result.summary = response.content[:500]

        except Exception as e:
            log.warning(f"Web research failed: {e}")

        # Deduplicate packages
        result.recommended_packages = list(dict.fromkeys(result.recommended_packages))
        result.recommended_system_packages = list(dict.fromkeys(result.recommended_system_packages))

        log.info(f"Research result: pip={result.recommended_packages}, "
                 f"apt={result.recommended_system_packages}")

        return result

    async def _generate_skill_code(
        self,
        capability: str,
        research: ResearchResult,
        failure_context: str = "",
    ) -> SkillDraft:
        """Generate skill code based on research and past failures."""
        log.info(f"Generating skill code for: {capability}")

        # Build prompt with research context
        packages_info = ""
        if research.recommended_packages:
            packages_info = f"\nRecommended packages: {', '.join(research.recommended_packages)}"

        # Check for stdlib recommendations
        stdlib_info = ""
        capability_lower = capability.lower()
        for hint_key, hint_val in CAPABILITY_PACKAGE_HINTS.items():
            if hint_key in capability_lower or capability_lower in hint_key:
                stdlib_modules = hint_val.get("stdlib", [])
                if stdlib_modules:
                    stdlib_info = f"\nStandard library alternative: {', '.join(stdlib_modules)} — use if appropriate for the task."
                    break

        examples_info = ""
        if research.code_examples:
            examples_info = f"\nCode examples from research:\n```python\n{research.code_examples[0][:1000]}\n```"

        # Include failure context if available
        failure_section = ""
        if failure_context:
            failure_section = f"\n{failure_context}\n"

        approach_info = ""
        if research.summary:
            approach_info = f"\nRecommended approach: {research.summary}"

        prompt = f"""Create a Python skill for: {capability}

{packages_info}
{stdlib_info}
{approach_info}
{examples_info}
{failure_section}
Requirements:
1. Create a function called `execute(input_data: dict) -> dict`
2. The function should take input_data with relevant parameters
3. Return a dict with 'success': bool and 'result': the output
4. Handle errors gracefully and return {{'success': False, 'error': str}}
5. Include necessary imports at the top
6. When a standard library module can fully solve the task, prefer it (e.g. csv for simple files, json instead of orjson). But use the right tool — external databases need proper drivers, complex formats need specialized libraries.
7. Use the recommended packages from research when they fit the task

For {capability}, the input_data might contain:
- file_path: path to a file to process
- content: raw content to process
- options: processing options

Return ONLY the Python code, no explanations. The code must be complete and runnable."""

        response = await self._get_code_gen_llm().chat(
            messages=[
                {"role": "system", "content": "You are an expert Python developer. Write clean, working code."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=4000,
        )

        # Extract code from response
        code = self._extract_code(response.content)

        # Extract imports to determine pip requirements
        imports = self._extract_imports(code)
        pip_requirements = self._imports_to_packages(imports, research.recommended_packages)

        # Generate skill name
        skill_name = f"skill_{capability.lower().replace(' ', '_').replace('-', '_')}"

        return SkillDraft(
            name=skill_name,
            description=f"Auto-generated skill for: {capability}",
            code=code,
            pip_requirements=pip_requirements,
            system_packages=research.recommended_system_packages,
            function_name="execute",
            interface=await self._derive_interface_with_llm(code, capability),
        )

    _LIBRARY_ALTERNATIVES: dict[str, list[tuple[str, str]]] = {
        "whisper": [
            ("faster-whisper", "CTranslate2-basiert, weniger RAM, schneller als openai-whisper"),
            ("speech_recognition", "Wrapper für CMU Sphinx (offline) oder Google STT"),
        ],
        "openai-whisper": [
            ("faster-whisper", "CTranslate2-basiert, weniger RAM, schneller als openai-whisper"),
            ("speech_recognition", "Wrapper für CMU Sphinx (offline) oder Google STT"),
        ],
        "torch": [
            ("onnxruntime", "Leichtgewichtige Inferenz ohne PyTorch"),
        ],
        "tensorflow": [
            ("onnxruntime", "Leichtgewichtige Inferenz ohne TensorFlow"),
            ("scikit-learn", "Klassisches ML ohne Deep-Learning-Framework"),
        ],
        "pandas": [
            ("polars", "Schnellere DataFrame-Library ohne C-Dependencies"),
        ],
        "psycopg2": [
            ("psycopg2-binary", "Vorkompiliert, braucht keine Build-Tools"),
            ("asyncpg", "Async PostgreSQL-Driver"),
        ],
        "mysql": [
            ("pymysql", "Pure-Python MySQL-Driver"),
        ],
        "PIL": [
            ("pillow", "Maintained Fork von PIL"),
        ],
        "cv2": [
            ("opencv-python-headless", "OpenCV ohne GUI-Dependencies"),
        ],
        "lxml": [
            ("beautifulsoup4", "HTML/XML-Parsing ohne C-Compiler"),
        ],
    }

    def _find_alternative_libraries(self, failed_lib: str) -> list[tuple[str, str]]:
        """Liefert alternative Libraries wenn die aktuelle wiederholt scheitert."""
        normalized = failed_lib.lower().replace("-", "_").replace("openai_whisper", "openai-whisper")
        for key, alternatives in self._LIBRARY_ALTERNATIVES.items():
            if normalized in key.lower().replace("-", "_") or key.lower().replace("-", "_") in normalized:
                return [(pkg, desc) for pkg, desc in alternatives if pkg.lower().replace("-", "_") != normalized]
        return []

    def _detect_libraries(self, code: str) -> list[str]:
        """Detect third-party library names used in code."""
        libs = []
        for line in code.split("\n"):
            line = line.strip()
            if line.startswith("import ") or line.startswith("from "):
                # Extract top-level module
                parts = line.replace("import ", "").replace("from ", "").split()[0].split(".")[0]
                if parts not in ("os", "sys", "json", "re", "math", "datetime", "sqlite3",
                                 "csv", "io", "pathlib", "collections", "typing", "uuid",
                                 "hashlib", "base64", "time", "random", "statistics",
                                 "functools", "itertools", "dataclasses", "enum", "copy"):
                    libs.append(parts)
        return list(set(libs))

    async def _fix_skill_code(
        self,
        draft: SkillDraft,
        error: str,
        research: ResearchResult,
        analysis: Optional[FailureAnalysis] = None,
        iteration_errors: Optional[list[dict]] = None,
    ) -> SkillDraft:
        """Attempt to fix skill code based on error message and analysis."""
        iteration_errors = iteration_errors or []
        log.info(f"Attempting to fix skill code based on error (attempt {len(iteration_errors)})")

        # Use analysis if available
        if analysis:
            # Handle import errors with suggested packages
            if analysis.error_type == ErrorType.IMPORT_ERROR:
                for package in analysis.alternative_packages:
                    if package not in draft.pip_requirements:
                        log.info(f"Adding suggested package: {package}")
                        draft.pip_requirements.append(package)
                        return draft

        # Check for pip install failures — remove bad package names
        if "No matching distribution found for" in error:
            match = re.search(r"No matching distribution found for (\S+)", error)
            if match:
                bad_package = match.group(1)
                log.info(f"Removing bad pip package: {bad_package}")
                draft.pip_requirements = [
                    p for p in draft.pip_requirements if p != bad_package
                ]
                # Try to find the correct package via mapping
                from app.skills.testing.package_resolver import HARDCODED_MAPPINGS
                corrected = HARDCODED_MAPPINGS.get(bad_package)
                if corrected and corrected not in draft.pip_requirements:
                    log.info(f"Replacing with correct package: {corrected}")
                    draft.pip_requirements.append(corrected)

        # Check for common errors (fallback if no analysis)
        if "ModuleNotFoundError" in error or "No module named" in error:
            # Extract missing module
            match = re.search(r"No module named ['\"]?(\w+)['\"]?", error)
            if match:
                missing_module = match.group(1)
                log.info(f"Missing module detected: {missing_module}")

                # Try to find the correct pip package
                package_name = self._module_to_package(missing_module)
                if package_name and package_name not in draft.pip_requirements:
                    draft.pip_requirements.append(package_name)
                    return draft

        # Build enhanced prompt with analysis suggestions
        analysis_section = ""
        if analysis:
            if analysis.suggested_fixes:
                analysis_section += f"\n**Suggested fixes:**\n"
                for fix in analysis.suggested_fixes[:3]:
                    analysis_section += f"- {fix}\n"
            if analysis.code_suggestions:
                analysis_section += f"\n**Code suggestions:**\n"
                for suggestion in analysis.code_suggestions[:2]:
                    analysis_section += f"- {suggestion}\n"

        # Build error history section
        error_history_section = ""
        if len(iteration_errors) >= 2:
            history_lines = []
            for e in iteration_errors:
                libs = ", ".join(e["libraries"]) if e["libraries"] else "stdlib only"
                history_lines.append(f"  Attempt {e['iteration']} (using {libs}): {e['error'][:150]}")
            error_history_section = f"\n\n**Previous failed attempts ({len(iteration_errors)} total):**\n" + "\n".join(history_lines)
            error_history_section += "\n\nDo NOT repeat these same mistakes."

        # Detect if the same library keeps failing → force approach switch
        approach_switch_section = ""
        if len(iteration_errors) >= 3:
            recent_libs = [lib for e in iteration_errors[-3:] for lib in e["libraries"]]
            if recent_libs:
                from collections import Counter
                lib_counts = Counter(recent_libs)
                repeated_lib, count = lib_counts.most_common(1)[0]
                if count >= 3:
                    log.info(f"Forcing approach switch: {repeated_lib} failed {count} times")

                    alternatives = self._find_alternative_libraries(repeated_lib)
                    if alternatives:
                        alt_text = "\n".join(f"- {pkg}: {desc}" for pkg, desc in alternatives)
                        approach_switch_section = f"""

CRITICAL: '{repeated_lib}' has failed {count} consecutive times.
You MUST switch to one of these alternative libraries:
{alt_text}

Pick the simplest alternative that works. Do NOT import {repeated_lib}."""
                    else:
                        approach_switch_section = f"""

CRITICAL: You have tried using '{repeated_lib}' for {count} consecutive attempts and it keeps failing.
You MUST ABANDON '{repeated_lib}' completely and use a DIFFERENT approach:
- For database operations: use the built-in sqlite3 module with raw SQL strings (CREATE TABLE, INSERT, SELECT)
- For data processing: use Python standard library (csv, json, collections)
- For file operations: use built-in open(), pathlib
- For math/statistics: use math, statistics modules
Do NOT import {repeated_lib} in your fixed code."""

                    # Remove the failing package from requirements
                    draft.pip_requirements = [
                        p for p in draft.pip_requirements
                        if repeated_lib not in p.lower().replace("-", "_")
                    ]

        # Use LLM to fix the code
        prompt = f"""Fix this Python code that has an error.

Original code:
```python
{draft.code}
```

Error message:
```
{error[:1000]}
```

Error type: {analysis.error_type.value if analysis else 'unknown'}
Root cause: {analysis.root_cause if analysis else 'Unknown'}
{analysis_section}{error_history_section}{approach_switch_section}

Fix the code to resolve this error. Return ONLY the fixed Python code, no explanations."""

        response = await self._get_code_gen_llm().chat(
            messages=[
                {"role": "system", "content": "You are an expert Python debugger. Fix the code."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=4000,
        )

        # Extract fixed code
        fixed_code = self._extract_code(response.content)

        # Update imports/requirements
        imports = self._extract_imports(fixed_code)
        new_requirements = self._imports_to_packages(imports, research.recommended_packages)

        # Add alternative packages from analysis
        if analysis and analysis.alternative_packages:
            for pkg in analysis.alternative_packages:
                if pkg not in new_requirements and pkg not in draft.pip_requirements:
                    new_requirements.append(pkg)

        # Merge requirements
        all_requirements = list(dict.fromkeys(draft.pip_requirements + new_requirements))

        return SkillDraft(
            name=draft.name,
            description=draft.description,
            code=fixed_code,
            pip_requirements=all_requirements,
            system_packages=draft.system_packages,
            function_name=draft.function_name,
            interface=await self._derive_interface_with_llm(fixed_code, draft.name),
        )

    def _build_test_code(
        self,
        draft: SkillDraft,
        test_input: Optional[dict],
        expected_output_type: str,
    ) -> str:
        """Build test code for the skill."""
        test_input = test_input or {}
        # Use json.dumps for the JSON string, but load it via json.loads() in
        # the generated code to avoid JSON true/false/null in Python context
        input_json = json.dumps(test_input).replace("\\", "\\\\").replace("'", "\\'")

        # If no test_input provided, run an import/callable check instead
        # of trying to execute with empty/dummy data that will fail
        if not test_input:
            return f'''
# Smoke test: verify imports work and execute() is callable
if __name__ == "__main__":
    import json
    import inspect

    # Verify execute function exists and is callable
    if not callable(execute):
        print("ERROR: execute is not callable")
        exit(1)

    sig = inspect.signature(execute)
    print(f"Function signature: execute{{sig}}")
    print("All imports successful, execute() is callable")
    print("TEST PASSED")
    exit(0)
'''

        # Prüfe ob Dateien verarbeitet werden sollen
        has_file_input = any(
            k in (test_input or {}) for k in ("file_path", "file", "input_file", "audio_file")
        )

        return f'''
# Test the skill
if __name__ == "__main__":
    import json
    import inspect

    test_input = json.loads('{input_json}')
    print("Testing skill with input:", test_input)

    # Signatur prüfen — execute() muss die übergebenen Keys akzeptieren
    sig = inspect.signature(execute)
    params = sig.parameters
    accepts_kwargs = any(p.kind == p.VAR_KEYWORD for p in params.values())
    if not accepts_kwargs:
        for key in test_input:
            if key not in params:
                print(f"ERROR: execute() akzeptiert Parameter '{{key}}' nicht (Signatur: {{sig}})")
                exit(1)

    try:
        # Aufruf mit Keyword-Arguments statt positionellem dict
        result = execute(**test_input)
        print("Result:", result)
        result_str = json.dumps(result, default=str) if isinstance(result, (dict, list)) else str(result)

        # Grundvalidierung
        if result is None:
            print("ERROR: Ergebnis ist None")
            exit(1)

        if isinstance(result, dict):
            # Fehler-Erkennung
            if result.get("error") and not result.get("text") and not result.get("result"):
                print(f"TEST FAILED: Skill meldet Fehler: {{result.get('error')}}")
                exit(1)

        # Anti-Gaming: Ergebnis muss substanziell sein (nicht nur Config/Flags)
        content_len = len(result_str)
        if content_len < 50:
            print(f"ERROR: Ergebnis zu kurz ({{content_len}} Zeichen) — Skill verarbeitet Input nicht wirklich")
            exit(1)

        {"" if not has_file_input else '''
        # Dateiverarbeitung: Ergebnis muss echten Inhalt enthalten
        if isinstance(result, dict):
            text_content = result.get("text") or result.get("result") or result.get("transcription") or result.get("content") or ""
            if isinstance(text_content, str) and len(text_content) < 20:
                print(f"ERROR: Skill hat Datei nicht verarbeitet — Textinhalt fehlt oder zu kurz ({len(text_content)} Zeichen)")
                exit(1)
        '''}

        print("TEST PASSED")
        exit(0)

    except Exception as e:
        print(f"EXCEPTION: {{type(e).__name__}}: {{e}}")
        exit(1)
'''

    def _generate_requirements_txt(self, pip_requirements: list[str]) -> str:
        """
        Generate requirements.txt content from pip requirements.

        Produces a formatted requirements.txt with comments and version hints.
        """
        if not pip_requirements:
            return ""

        lines = [
            "# Auto-generated requirements.txt",
            f"# Generated at: {datetime.now(timezone.utc).isoformat()}",
            "#",
        ]

        for pkg in pip_requirements:
            # Add package (could add version pinning logic here)
            lines.append(pkg)

        return "\n".join(lines)

    async def _persist_skill(
        self,
        draft: SkillDraft,
        research: ResearchResult,
        iterations: int,
    ) -> Skill:
        """Persist the successful skill to database."""
        log.info(f"Persisting skill: {draft.name}")

        # Generate requirements.txt
        requirements_txt = self._generate_requirements_txt(draft.pip_requirements)

        # Build metadata
        metadata = {
            "pip_requirements": draft.pip_requirements,
            "system_packages": draft.system_packages,
            "requirements_txt": requirements_txt,
            "research_sources": research.sources,
            "build_iterations": iterations,
            "auto_generated": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "affected_capability": draft.name.replace("skill_", "").replace("_", " "),
        }

        async with self.session_factory() as db:
            # Check if skill already exists
            existing = await db.execute(
                select(Skill).where(Skill.name == draft.name)
            )
            existing_skill = existing.scalar_one_or_none()

            # applicability aus affected_capability ableiten (SoK C-Feld)
            applicability = metadata.get("affected_capability", draft.name.replace("skill_", "").replace("_", " "))

            if existing_skill:
                # Update existing skill
                existing_skill.code = draft.code
                existing_skill.description = draft.description
                existing_skill.interface = draft.interface or existing_skill.interface
                existing_skill.skill_metadata = metadata
                existing_skill.applicability = applicability
                existing_skill.is_active = True
                await db.commit()
                log.info(f"Updated existing skill: {existing_skill.id}")
                return existing_skill

            # Create new skill
            skill = Skill(
                id=str(uuid.uuid4()),
                name=draft.name,
                description=draft.description,
                code=draft.code,
                test_cases=[],
                interface=draft.interface,
                skill_metadata=metadata,
                applicability=applicability,
                is_active=True,
            )

            db.add(skill)
            await db.commit()
            await db.refresh(skill)

            log.info(f"Created new skill: {skill.id}")
            return skill

    async def _derive_interface_with_llm(self, code: str, capability: str) -> dict:
        """Use LLM + Instructor to derive accurate interface from generated code."""
        prompt = f"""Analyze this Python skill code and extract its interface schema.

The function `execute(input_data: dict)` reads parameters from `input_data`.
For each parameter found, determine the correct type:
- "file" for file paths (parameters containing file/path in name, or used with open())
- "object" for dict parameters (used with .get(), ["key"], .keys(), .items())
- "array" for list parameters (iterated over, used with .append(), len())
- "integer" / "number" for numeric parameters
- "boolean" for flag parameters
- "string" for text parameters

Mark parameters as required if the code does not provide a default value (i.e. uses input_data["key"] instead of input_data.get("key", default)).

```python
{code}
```"""

        try:
            result: SkillInterfaceOutput = await self.llm.chat_structured(
                messages=[
                    {"role": "system", "content": "You are a code analyzer. Extract parameter interfaces accurately."},
                    {"role": "user", "content": prompt},
                ],
                response_model=SkillInterfaceOutput,
                temperature=0.1,
                max_tokens=1000,
            )
            return {
                "input": result.input.model_dump(),
                "output": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "result": {"type": "object"},
                    },
                },
            }
        except Exception as e:
            log.warning(f"LLM interface derivation failed for '{capability}': {e}, falling back to regex")
            return self._derive_interface_from_code(code)

    @staticmethod
    def _derive_interface_from_code(code: str) -> dict:
        """Derive an interface schema from the execute() function signature via AST (fallback)."""
        import ast
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return {}

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name != "execute":
                continue

            # Parse docstring for parameter descriptions
            docstring = ast.get_docstring(node) or ""
            param_descriptions: dict[str, str] = {}
            for line in docstring.split("\n"):
                line = line.strip()
                # Match "param_name: description" or "param_name (type): description"
                if ":" in line and not line.startswith("Args") and not line.startswith("Returns"):
                    parts = line.split(":", 1)
                    key = parts[0].strip().strip("-").strip()
                    if key and not key[0].isupper() and len(parts) > 1:
                        param_descriptions[key] = parts[1].strip()

            # Check if function takes a single dict param (input_data: dict)
            args = node.args
            params = args.args
            if len(params) == 1:
                # Single dict param — look at docstring/code for inner keys
                properties: dict[str, dict] = {}
                # Scan code for input_data.get("key") or input_data["key"] patterns
                import re
                for match in re.finditer(r'input_data(?:\.get\(|\.?\[)["\'](\w+)["\']', code):
                    key = match.group(1)
                    ptype = "file" if "file" in key or "path" in key else "string"
                    properties[key] = {
                        "type": ptype,
                        "description": param_descriptions.get(key, ""),
                    }

                if properties:
                    return {
                        "input": {
                            "type": "object",
                            "properties": properties,
                            "required": list(properties.keys())[:1],  # First param as required
                        },
                        "output": {
                            "type": "object",
                            "properties": {
                                "success": {"type": "boolean"},
                                "result": {"type": "object"},
                            },
                        },
                    }
            break

        return {}

    def _parse_skill_output(self, stdout: str) -> Any:
        """Parse skill output from sandbox stdout."""
        try:
            # Try to find the result line
            lines = stdout.strip().split('\n')
            for line in reversed(lines):
                if line.startswith('Result:'):
                    # Extract dict/value after 'Result:'
                    result_str = line[7:].strip()
                    try:
                        return json.loads(result_str.replace("'", '"'))
                    except json.JSONDecodeError:
                        return result_str

            # Try to parse entire stdout as JSON
            try:
                return json.loads(stdout)
            except json.JSONDecodeError:
                pass

            # Return raw stdout
            return stdout.strip()

        except Exception as e:
            log.warning(f"Failed to parse skill output: {e}")
            return stdout

    def _extract_code(self, response: str) -> str:
        """Extract Python code from LLM response."""
        # Try to find code in markdown blocks
        code_match = re.search(r'```python\n(.*?)```', response, re.DOTALL)
        if code_match:
            return code_match.group(1).strip()

        code_match = re.search(r'```\n(.*?)```', response, re.DOTALL)
        if code_match:
            return code_match.group(1).strip()

        # If no code blocks, assume the whole response is code
        # Remove any leading/trailing non-code text
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

    def _extract_imports(self, code: str) -> list[str]:
        """Extract imported module names from code."""
        imports = []

        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name.split('.')[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.append(node.module.split('.')[0])
        except SyntaxError:
            # Fallback to regex
            import_matches = re.findall(r'^import\s+(\w+)', code, re.MULTILINE)
            from_matches = re.findall(r'^from\s+(\w+)', code, re.MULTILINE)
            imports = import_matches + from_matches

        return list(set(imports))

    async def _imports_to_packages_async(
        self,
        imports: list[str],
        recommended: list[str],
    ) -> list[str]:
        """Convert import names to pip package names using PackageResolver."""
        # Lazy-init PackageResolver mit frischer Session
        if self.package_resolver is None:
            async with self.session_factory() as db:
                self.package_resolver = PackageResolver(db)

        packages = []

        for imp in imports:
            # Skip stdlib
            if self.package_resolver.is_stdlib(imp):
                continue

            # Resolve using PackageResolver
            package = await self.package_resolver.resolve(imp)
            if package:
                packages.append(package)

        # Add recommended packages that weren't in imports but are needed
        for pkg in recommended:
            pkg_lower = pkg.lower().replace('-', '_')
            if pkg not in packages and any(pkg_lower in imp.lower() for imp in imports):
                packages.append(pkg)

        return list(dict.fromkeys(packages))

    def _imports_to_packages(
        self,
        imports: list[str],
        recommended: list[str],
    ) -> list[str]:
        """Convert import names to pip package names (sync fallback)."""
        # Use hardcoded mappings for sync context
        from app.skills.testing.package_resolver import HARDCODED_MAPPINGS, STDLIB_MODULES

        packages = []

        for imp in imports:
            if imp in STDLIB_MODULES:
                continue

            # Check mapping
            if imp in HARDCODED_MAPPINGS:
                packages.append(HARDCODED_MAPPINGS[imp])
            elif imp in recommended:
                packages.append(imp)
            else:
                # Assume import name == package name
                packages.append(imp)

        # Add recommended packages that weren't in imports but are needed
        for pkg in recommended:
            pkg_lower = pkg.lower().replace('-', '_')
            if pkg not in packages and any(pkg_lower in imp.lower() for imp in imports):
                packages.append(pkg)

        return list(dict.fromkeys(packages))

    def _module_to_package(self, module: str) -> Optional[str]:
        """Convert a module name to its pip package name (sync fallback)."""
        from app.skills.testing.package_resolver import HARDCODED_MAPPINGS

        if module in HARDCODED_MAPPINGS:
            return HARDCODED_MAPPINGS[module]

        # Default: assume module name is package name
        return module

    async def _module_to_package_async(self, module: str) -> Optional[str]:
        """Convert a module name to its pip package name using PackageResolver."""
        return await self.package_resolver.resolve(module)
