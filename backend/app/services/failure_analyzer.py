"""
Failure Analyzer Service - Learn from skill build failures.

This service implements failure pattern recognition and learning:
1. Classify errors by type (import, syntax, structure, runtime, semantic)
2. Extract failure patterns
3. Suggest alternative approaches
4. Persist failure data for future learning
"""

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass, field

from sqlalchemy import select, func, desc

from app.models.sql.skill_build_models import SkillBuildAttempt, PackageMapping
from app.models.schemas.skill_build_schemas import ErrorType, FailurePattern
from app.core.llm_client import LLMClient

log = logging.getLogger(__name__)


@dataclass
class FailureAnalysis:
    """Result of analyzing a failure."""
    error_type: ErrorType
    error_category: str  # More specific category within error_type
    root_cause: str
    suggested_fixes: list[str] = field(default_factory=list)
    alternative_packages: list[str] = field(default_factory=list)
    code_suggestions: list[str] = field(default_factory=list)
    confidence: float = 0.5  # 0-1, how confident we are in this analysis
    similar_past_failures: list[dict] = field(default_factory=list)
    error_type_classified: str = ""   # IMPORT_ERROR, STRUCTURE_ERROR, LOGIC_ERROR
    lesson_learned: str = ""          # LLM-generated insight from this failure


@dataclass
class StrategyProposal:
    """Proposed next strategy based on build history."""
    strategy_id: str                    # e.g. "alt_package", "simplify", "restructure"
    rationale: str                      # Why this strategy was chosen
    related_attempt_ids: list[str] = field(default_factory=list)  # History entries referenced
    confidence: float = 0.5            # 0-1
    hints: list[str] = field(default_factory=list)  # Concrete tips for the builder


class FailureAnalyzer:
    """
    Analyzes skill build failures to learn and improve future attempts.

    Key capabilities:
    - Classify errors into actionable types
    - Find patterns in failures
    - Suggest fixes based on past successes
    - Record failures for future learning
    """

    # Strategy candidates per classified error type
    STRATEGY_MAP = {
        "IMPORT_ERROR": ["alt_package", "minimal_imports", "stdlib_only"],
        "STRUCTURE_ERROR": ["ast_fix", "template_rewrite"],
        "LOGIC_ERROR": ["simplify", "decompose", "reference_impl"],
    }
    DEFAULT_STRATEGIES = ["direct", "simplify", "alternative", "from_scratch"]

    # Map fine-grained ErrorType to coarse classification
    ERROR_TYPE_CLASSIFICATION = {
        ErrorType.IMPORT_ERROR: "IMPORT_ERROR",
        ErrorType.DEPENDENCY_ERROR: "IMPORT_ERROR",
        ErrorType.SYNTAX_ERROR: "STRUCTURE_ERROR",
        ErrorType.STRUCTURE_ERROR: "STRUCTURE_ERROR",
        ErrorType.RUNTIME_ERROR: "LOGIC_ERROR",
        ErrorType.TIMEOUT_ERROR: "LOGIC_ERROR",
        ErrorType.RESOURCE_ERROR: "LOGIC_ERROR",
        ErrorType.SEMANTIC_ERROR: "LOGIC_ERROR",
    }

    # Error patterns for classification
    ERROR_PATTERNS = {
        ErrorType.IMPORT_ERROR: [
            r"ModuleNotFoundError: No module named '(\w+)'",
            r"ImportError: cannot import name '(\w+)'",
            r"ImportError: No module named (\w+)",
        ],
        ErrorType.SYNTAX_ERROR: [
            r"SyntaxError: (.+)",
            r"IndentationError: (.+)",
            r"TabError: (.+)",
        ],
        ErrorType.RUNTIME_ERROR: [
            r"TypeError: (.+)",
            r"ValueError: (.+)",
            r"KeyError: (.+)",
            r"AttributeError: (.+)",
            r"IndexError: (.+)",
            r"NameError: (.+)",
            r"ZeroDivisionError: (.+)",
            r"FileNotFoundError: (.+)",
            r"PermissionError: (.+)",
        ],
        ErrorType.TIMEOUT_ERROR: [
            r"timed out",
            r"TimeoutError",
            r"timeout",
        ],
        ErrorType.RESOURCE_ERROR: [
            r"MemoryError",
            r"OOM",
            r"out of memory",
            r"disk.*full",
            r"no space left",
        ],
        ErrorType.DEPENDENCY_ERROR: [
            r"version conflict",
            r"incompatible",
            r"requires",
            r"dependency",
            r"pip.*error",
            r"apt-get.*error",
        ],
        ErrorType.STRUCTURE_ERROR: [
            r"Missing required.*def execute",
            r"execute\(\) must accept",
            r"Structure error",
            r"no.*execute.*function",
            r"def execute.*not found",
        ],
    }

    def __init__(
        self,
        session_factory,
        llm_client: Optional[LLMClient] = None,
    ):
        """
        Initialize the failure analyzer.

        Args:
            session_factory: Async session factory for DB access
            llm_client: Optional LLM for deeper analysis
        """
        self.session_factory = session_factory
        self.llm = llm_client

    def classify_error(self, error_message: str, stderr: str = "") -> ErrorType:
        """
        Classify an error into a specific type.

        Args:
            error_message: The main error message
            stderr: Full stderr output

        Returns:
            ErrorType classification
        """
        full_text = f"{error_message}\n{stderr}".lower()

        for error_type, patterns in self.ERROR_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, full_text, re.IGNORECASE):
                    return error_type

        # Default to runtime if can't classify
        return ErrorType.RUNTIME_ERROR

    def classify_error_coarse(self, error_type: ErrorType) -> str:
        """Map fine-grained ErrorType to coarse classification (IMPORT/STRUCTURE/LOGIC)."""
        return self.ERROR_TYPE_CLASSIFICATION.get(error_type, "LOGIC_ERROR")

    def extract_missing_module(self, error_message: str) -> Optional[str]:
        """Extract the missing module name from import error."""
        patterns = [
            r"No module named ['\"]?(\w+)['\"]?",
            r"ModuleNotFoundError: No module named ['\"]?(\w+)['\"]?",
            r"ImportError: No module named (\w+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, error_message)
            if match:
                return match.group(1)

        return None

    async def analyze_failure(
        self,
        capability: str,
        code: str,
        error_message: str,
        stderr: str = "",
        pip_requirements: Optional[list[str]] = None,
    ) -> FailureAnalysis:
        """
        Perform comprehensive failure analysis.

        Args:
            capability: What capability was being built
            code: The code that failed
            error_message: Error message
            stderr: Full stderr
            pip_requirements: Packages that were tried

        Returns:
            FailureAnalysis with suggestions
        """
        pip_requirements = pip_requirements or []

        # Classify error
        error_type = self.classify_error(error_message, stderr)

        # Get analysis based on error type
        analysis = FailureAnalysis(
            error_type=error_type,
            error_category="",
            root_cause="",
        )

        if error_type == ErrorType.IMPORT_ERROR:
            analysis = await self._analyze_import_error(
                error_message, stderr, pip_requirements
            )
        elif error_type == ErrorType.SYNTAX_ERROR:
            analysis = self._analyze_syntax_error(error_message, code)
        elif error_type == ErrorType.STRUCTURE_ERROR:
            analysis = self._analyze_structure_error(error_message, code)
        elif error_type == ErrorType.RUNTIME_ERROR:
            analysis = await self._analyze_runtime_error(
                error_message, stderr, code
            )
        elif error_type == ErrorType.DEPENDENCY_ERROR:
            analysis = await self._analyze_dependency_error(
                error_message, stderr, pip_requirements
            )
        else:
            analysis.error_category = error_type.value
            analysis.root_cause = error_message[:200]

        # Set coarse classification and lesson learned
        analysis.error_type_classified = self.classify_error_coarse(error_type)
        analysis.lesson_learned = (
            f"{analysis.error_type_classified}: {analysis.root_cause[:150]}. "
            f"Fix: {analysis.suggested_fixes[0]}" if analysis.suggested_fixes
            else f"{analysis.error_type_classified}: {analysis.root_cause[:200]}"
        )

        # Find similar past failures
        similar = await self._find_similar_failures(capability, error_type)
        analysis.similar_past_failures = similar

        # If we have similar failures that were later fixed, extract suggestions
        if similar:
            for past in similar:
                if past.get("later_success") and past.get("fix_approach"):
                    analysis.suggested_fixes.append(past["fix_approach"])

        return analysis

    async def _analyze_import_error(
        self,
        error_message: str,
        stderr: str,
        pip_requirements: list[str],
    ) -> FailureAnalysis:
        """Analyze import error and suggest package fixes."""
        analysis = FailureAnalysis(
            error_type=ErrorType.IMPORT_ERROR,
            error_category="missing_module",
            root_cause="",
        )

        # Extract missing module
        missing_module = self.extract_missing_module(error_message)
        if missing_module:
            analysis.root_cause = f"Missing module: {missing_module}"

            # Check if we have a known mapping
            async with self.session_factory() as db:
                result = await db.execute(
                    select(PackageMapping).where(
                        PackageMapping.module_name == missing_module
                    )
                )
                mapping = result.scalar_one_or_none()

            if mapping:
                # Use known mapping
                if mapping.package_name not in pip_requirements:
                    analysis.alternative_packages.append(mapping.package_name)
                    analysis.suggested_fixes.append(
                        f"Install package: {mapping.package_name}"
                    )
                # Also suggest alternatives
                for alt in (mapping.alternatives or [])[:3]:
                    if alt not in pip_requirements:
                        analysis.alternative_packages.append(alt)
                analysis.confidence = mapping.confidence
            else:
                # Try to guess package name
                analysis.alternative_packages.append(missing_module)
                analysis.suggested_fixes.append(
                    f"Try installing: {missing_module}"
                )
                analysis.confidence = 0.3

        return analysis

    def _analyze_syntax_error(
        self,
        error_message: str,
        code: str,
    ) -> FailureAnalysis:
        """Analyze syntax error."""
        analysis = FailureAnalysis(
            error_type=ErrorType.SYNTAX_ERROR,
            error_category="invalid_syntax",
            root_cause=error_message[:200],
        )

        # Extract line number if available
        line_match = re.search(r"line (\d+)", error_message)
        if line_match:
            line_num = int(line_match.group(1))
            lines = code.split("\n")
            if 0 < line_num <= len(lines):
                problematic_line = lines[line_num - 1]
                analysis.code_suggestions.append(
                    f"Check line {line_num}: {problematic_line[:80]}"
                )

        analysis.suggested_fixes.append("Regenerate code with proper Python syntax")
        analysis.confidence = 0.7

        return analysis

    def _analyze_structure_error(
        self,
        error_message: str,
        code: str,
    ) -> FailureAnalysis:
        """Analyze structure error (missing execute function, wrong signature)."""
        analysis = FailureAnalysis(
            error_type=ErrorType.STRUCTURE_ERROR,
            error_category="missing_execute",
            root_cause=error_message[:200],
            confidence=0.9,
        )

        # Check what's actually defined at top level
        import ast
        try:
            tree = ast.parse(code)
            top_level_funcs = [
                node.name for node in ast.iter_child_nodes(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
        except SyntaxError:
            top_level_funcs = []

        if top_level_funcs:
            analysis.error_category = "wrong_function_name"
            analysis.root_cause = (
                f"Code defines {top_level_funcs} but not `execute`. "
                f"Rename the main function to `execute`."
            )
            analysis.suggested_fixes.append(
                f"Rename `{top_level_funcs[0]}` to `execute`"
            )
        else:
            analysis.error_category = "missing_execute"
            analysis.root_cause = "No top-level function defined at all."
            analysis.suggested_fixes.append(
                "Wrap implementation in `def execute(input_data: dict) -> dict:`"
            )

        analysis.suggested_fixes.append(
            "MANDATORY signature: def execute(input_data: dict) -> dict"
        )

        return analysis

    async def _analyze_runtime_error(
        self,
        error_message: str,
        stderr: str,
        code: str,
    ) -> FailureAnalysis:
        """Analyze runtime error."""
        analysis = FailureAnalysis(
            error_type=ErrorType.RUNTIME_ERROR,
            error_category="",
            root_cause=error_message[:200],
        )

        # Categorize runtime error
        full_text = f"{error_message}\n{stderr}"

        if "TypeError" in full_text:
            analysis.error_category = "type_mismatch"
            analysis.suggested_fixes.append("Check argument types")
        elif "ValueError" in full_text:
            analysis.error_category = "invalid_value"
            analysis.suggested_fixes.append("Validate input values")
        elif "KeyError" in full_text:
            analysis.error_category = "missing_key"
            analysis.suggested_fixes.append("Add key existence check")
        elif "AttributeError" in full_text:
            analysis.error_category = "missing_attribute"
            analysis.suggested_fixes.append("Check object type and attributes")
        elif "FileNotFoundError" in full_text:
            analysis.error_category = "file_not_found"
            analysis.suggested_fixes.append("Verify file path exists")
        else:
            analysis.error_category = "general_runtime"

        analysis.confidence = 0.6

        return analysis

    async def _analyze_dependency_error(
        self,
        error_message: str,
        stderr: str,
        pip_requirements: list[str],
    ) -> FailureAnalysis:
        """Analyze dependency/package installation error."""
        analysis = FailureAnalysis(
            error_type=ErrorType.DEPENDENCY_ERROR,
            error_category="package_conflict",
            root_cause=error_message[:200],
        )

        # Try to extract conflicting packages
        conflict_patterns = [
            r"incompatible.*(\w+)",
            r"requires (\w+)",
            r"conflict.*(\w+)",
        ]

        for pattern in conflict_patterns:
            match = re.search(pattern, f"{error_message}\n{stderr}", re.IGNORECASE)
            if match:
                package = match.group(1)
                analysis.suggested_fixes.append(f"Check version of: {package}")

        analysis.suggested_fixes.append("Try installing packages one at a time")
        analysis.suggested_fixes.append("Check for version conflicts")
        analysis.confidence = 0.5

        return analysis

    async def _find_similar_failures(
        self,
        capability: str,
        error_type: ErrorType,
        limit: int = 5,
    ) -> list[dict]:
        """Find similar past failures for learning."""
        # Search for failures with same capability and error type
        async with self.session_factory() as db:
            result = await db.execute(
                select(SkillBuildAttempt)
                .where(
                    SkillBuildAttempt.capability.ilike(f"%{capability}%"),
                    SkillBuildAttempt.error_type == error_type.value,
                    SkillBuildAttempt.success == False,
                )
                .order_by(desc(SkillBuildAttempt.created_at))
                .limit(limit)
            )

            failures = result.scalars().all()

            similar = []
            for failure in failures:
                # Check if there was a later success for this capability
                success_result = await db.execute(
                    select(SkillBuildAttempt)
                    .where(
                        SkillBuildAttempt.capability == failure.capability,
                        SkillBuildAttempt.success == True,
                        SkillBuildAttempt.created_at > failure.created_at,
                    )
                    .limit(1)
                )
                later_success = success_result.scalar_one_or_none()

                similar.append({
                    "id": failure.id,
                    "error_message": failure.error_message[:200] if failure.error_message else "",
                    "pip_requirements": failure.pip_requirements or [],
                    "approach": failure.approach,
                    "later_success": later_success is not None,
                    "fix_approach": (
                        later_success.approach if later_success else None
                    ),
                })

        return similar

    async def propose_strategy(
        self,
        capability: str,
        error_type_classified: Optional[str] = None,
        current_attempt_number: int = 1,
    ) -> StrategyProposal:
        """
        Propose the next build strategy based on history.

        Looks at past attempts for this capability, checks which strategies
        have already been tried, and picks the next untried strategy
        appropriate for the error type.

        Args:
            capability: What capability is being built
            error_type_classified: Coarse error class (IMPORT_ERROR, STRUCTURE_ERROR, LOGIC_ERROR)
            current_attempt_number: Current attempt number

        Returns:
            StrategyProposal with recommended next strategy
        """
        # First attempt — always start with "direct"
        if current_attempt_number <= 1:
            return StrategyProposal(
                strategy_id="direct",
                rationale="First attempt — try direct implementation",
                confidence=0.5,
            )

        # Load history
        history = await self.get_failure_history(capability)
        tried_strategies = {
            a.strategy_id for a in history if a.strategy_id
        }
        related_ids = [a.id for a in history[:5]]

        # Collect lessons from history
        hints = []
        for attempt in history:
            if attempt.lesson_learned:
                hints.append(attempt.lesson_learned)

        # Pick strategy candidates based on error type
        candidates = self.STRATEGY_MAP.get(
            error_type_classified or "", self.DEFAULT_STRATEGIES
        )

        # Find first untried strategy
        for strategy in candidates:
            if strategy not in tried_strategies:
                return StrategyProposal(
                    strategy_id=strategy,
                    rationale=f"Strategy '{strategy}' not yet tried for {error_type_classified or 'this error type'}",
                    related_attempt_ids=related_ids,
                    confidence=0.6,
                    hints=hints[:3],
                )

        # All strategies tried — fall back to "from_scratch" with lessons
        return StrategyProposal(
            strategy_id="from_scratch",
            rationale=f"All {len(candidates)} strategies exhausted — starting fresh with accumulated lessons",
            related_attempt_ids=related_ids,
            confidence=0.3,
            hints=hints[:5],
        )

    async def record_attempt(
        self,
        capability: str,
        code: str,
        success: bool,
        error_type: Optional[ErrorType] = None,
        error_message: Optional[str] = None,
        stderr: Optional[str] = None,
        stdout: Optional[str] = None,
        pip_requirements: Optional[list[str]] = None,
        system_packages: Optional[list[str]] = None,
        approach: Optional[str] = None,
        team_role: Optional[str] = None,
        attempt_number: int = 1,
        execution_time_ms: int = 0,
        research_context: Optional[dict] = None,
        failure_analysis: Optional[dict] = None,
        skill_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
        error_type_classified: Optional[str] = None,
        lesson_learned: Optional[str] = None,
        related_attempt_ids: Optional[list[str]] = None,
    ) -> str:
        """
        Record a skill build attempt for learning.

        Args:
            capability: What was being built
            code: The code that was tried
            success: Whether it worked
            error_type: Classification of error (if failed)
            error_message: Error message (if failed)
            stderr: Full stderr
            stdout: Full stdout
            pip_requirements: Packages tried
            system_packages: System packages tried
            approach: Build approach used
            team_role: Which team role produced this
            attempt_number: Which attempt this was
            execution_time_ms: How long it took
            research_context: Research data used
            failure_analysis: Analysis of failure
            skill_id: ID of skill if successful
            strategy_id: Strategy used for this attempt
            error_type_classified: Coarse error class (IMPORT_ERROR, STRUCTURE_ERROR, LOGIC_ERROR)
            lesson_learned: LLM-generated insight from this attempt
            related_attempt_ids: IDs of earlier attempts that were referenced

        Returns:
            ID of the recorded attempt
        """
        attempt = SkillBuildAttempt(
            id=str(uuid.uuid4()),
            capability=capability,
            team_role=team_role,
            attempt_number=attempt_number,
            approach=approach,
            code_snapshot=code[:10000] if code else None,  # Truncate for storage
            pip_requirements=pip_requirements or [],
            system_packages=system_packages or [],
            success=success,
            error_type=error_type.value if error_type else None,
            error_message=error_message[:2000] if error_message else None,
            sandbox_stdout=stdout[:5000] if stdout else None,
            sandbox_stderr=stderr[:5000] if stderr else None,
            execution_time_ms=execution_time_ms,
            research_context=research_context,
            failure_analysis=failure_analysis,
            skill_id=skill_id,
            strategy_id=strategy_id,
            error_type_classified=error_type_classified,
            lesson_learned=lesson_learned,
            related_attempt_ids=related_attempt_ids or [],
        )

        async with self.session_factory() as db:
            db.add(attempt)
            await db.commit()

        log.info(
            f"Recorded build attempt: capability={capability}, "
            f"success={success}, error_type={error_type}"
        )

        return attempt.id

    async def get_failure_history(
        self,
        capability: str,
        limit: int = 10,
    ) -> list[SkillBuildAttempt]:
        """
        Get failure history for a capability.

        Returns recent failed attempts to help avoid repeating mistakes.
        """
        async with self.session_factory() as db:
            result = await db.execute(
                select(SkillBuildAttempt)
                .where(
                    SkillBuildAttempt.capability.ilike(f"%{capability}%"),
                    SkillBuildAttempt.success == False,
                )
                .order_by(desc(SkillBuildAttempt.created_at))
                .limit(limit)
            )

            return list(result.scalars().all())

    async def get_successful_approaches(
        self,
        capability: str,
        limit: int = 5,
    ) -> list[SkillBuildAttempt]:
        """
        Get successful approaches for similar capabilities.

        Helps guide future attempts with proven approaches.
        """
        async with self.session_factory() as db:
            result = await db.execute(
                select(SkillBuildAttempt)
                .where(
                    SkillBuildAttempt.capability.ilike(f"%{capability}%"),
                    SkillBuildAttempt.success == True,
                )
                .order_by(desc(SkillBuildAttempt.created_at))
                .limit(limit)
            )

            return list(result.scalars().all())

    async def learn_from_success(
        self,
        capability: str,
        pip_requirements: list[str],
        code: str,
    ) -> None:
        """
        Learn from a successful build to improve future attempts.

        Updates package mappings and research cache with successful data.
        """
        # Update package mapping confidence for used packages
        async with self.session_factory() as db:
            for package in pip_requirements:
                # Try to find which module this package provides
                # This is a simplified approach - could be improved with actual inspection
                module_name = package.replace("-", "_").lower()

                result = await db.execute(
                    select(PackageMapping).where(
                        PackageMapping.package_name == package
                    )
                )
                mapping = result.scalar_one_or_none()

                if mapping:
                    mapping.success_count += 1
                    mapping.confidence = min(1.0, mapping.confidence + 0.05)
                else:
                    # Check if this module is imported in the code
                    import re
                    import_patterns = [
                        rf"^import\s+{re.escape(module_name)}",
                        rf"^from\s+{re.escape(module_name)}",
                    ]

                    for pattern in import_patterns:
                        if re.search(pattern, code, re.MULTILINE | re.IGNORECASE):
                            # Create new mapping
                            new_mapping = PackageMapping(
                                id=str(uuid.uuid4()),
                                module_name=module_name,
                                package_name=package,
                                confidence=0.7,
                                source="learned",
                                success_count=1,
                            )
                            db.add(new_mapping)
                            log.info(f"Learned new package mapping: {module_name} -> {package}")
                            break

            await db.commit()

    def format_failure_context(
        self,
        failures: list[SkillBuildAttempt],
    ) -> str:
        """
        Format failure history for inclusion in prompts.

        Creates a readable summary of past failures to help LLM avoid them.
        """
        if not failures:
            return ""

        context = "**Previous Failed Attempts (try different approach):**\n\n"

        for i, failure in enumerate(failures[:5], 1):
            strategy = failure.strategy_id or failure.approach or 'unknown approach'
            context += f"{i}. **Attempt {failure.attempt_number}** (strategy: {strategy}):\n"
            context += f"   - Error: {failure.error_type or 'unknown'}\n"
            if failure.error_type_classified:
                context += f"   - Classification: {failure.error_type_classified}\n"
            if failure.error_message:
                context += f"   - Message: {failure.error_message[:150]}...\n"
            if failure.pip_requirements:
                context += f"   - Packages: {', '.join(failure.pip_requirements[:5])}\n"
            if failure.lesson_learned:
                context += f"   - Lesson: {failure.lesson_learned}\n"
            elif failure.failure_analysis:
                analysis = failure.failure_analysis
                if analysis.get("suggested_fixes"):
                    context += f"   - Suggested fix: {analysis['suggested_fixes'][0]}\n"
            context += "\n"

        return context
