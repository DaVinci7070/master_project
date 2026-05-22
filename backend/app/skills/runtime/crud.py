"""
Skill service for managing skills with test validation.

Implements DB-06: Skills cannot be activated unless their test cases pass.
This service integrates the SkillExecutor with skill CRUD operations.
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.models.sql.versioned_models import Skill
from app.repositories.skill_repository import SkillRepository
from app.skills.runtime.executor import SkillExecutor, TestResult

log = logging.getLogger(__name__)


class SkillValidationError(Exception):
    """
    Exception raised when skill validation fails.

    Contains detailed test results for debugging.
    """

    def __init__(self, message: str, test_results: List[TestResult] = None):
        super().__init__(message)
        self.message = message
        self.test_results = test_results or []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "message": self.message,
            "test_results": [
                {
                    "test_case_index": r.test_case_index,
                    "passed": r.passed,
                    "input_data": r.input_data,
                    "expected_output": r.expected_output,
                    "actual_output": r.actual_output,
                    "error": r.error,
                    "execution_time_ms": r.execution_time_ms,
                }
                for r in self.test_results
            ],
        }


class SkillService:
    """
    Service for skill management with integrated test validation.

    Key behavior (DB-06):
    - Skills cannot be activated unless all test cases pass
    - Creating/updating skills with validate=True runs tests first
    - activate() always validates before setting is_active=True

    Usage:
        service = SkillService(repository, executor)

        # Create with validation
        skill = await service.create(skill_data)

        # Explicitly activate (will validate)
        skill = await service.activate(skill_id)

        # Run tests without state change
        passed, results = await service.run_tests(skill_id)
    """

    def __init__(
        self,
        repository: SkillRepository,
        executor: Optional[SkillExecutor] = None,
    ):
        """
        Initialize skill service.

        Args:
            repository: SkillRepository for database operations
            executor: SkillExecutor for code execution (creates default if None)
        """
        self.repository = repository
        self.executor = executor or SkillExecutor()

    async def create(
        self,
        skill_data: Dict[str, Any],
        validate: bool = True,
        function_name: str = "execute",
    ) -> Skill:
        """
        Create a new skill, optionally validating tests first.

        If validate=True and test_cases are provided:
        - Tests are run against the code
        - is_active is set based on validation result
        - SkillValidationError is raised if tests fail and is_active was requested

        Args:
            skill_data: Dictionary with name, code, test_cases, etc.
            validate: Whether to validate tests before creation
            function_name: Function to call in skill code

        Returns:
            Created Skill instance

        Raises:
            SkillValidationError: If validation fails and is_active was requested
        """
        log.info(f"Creating skill: {skill_data.get('name', 'unnamed')}, validate={validate}")

        code = skill_data.get("code", "")
        test_cases = skill_data.get("test_cases", [])
        requested_active = skill_data.get("is_active", False)

        # Determine is_active based on validation
        is_active = False
        if validate and test_cases:
            passed, results = await self.executor.validate_skill(
                code, test_cases, function_name
            )
            if passed:
                is_active = requested_active
            elif requested_active:
                # Requested active but tests failed
                failed_count = sum(1 for r in results if not r.passed)
                raise SkillValidationError(
                    f"Cannot create active skill: {failed_count}/{len(results)} tests failed",
                    test_results=results,
                )
            # If tests failed but is_active not requested, create as inactive
        elif not test_cases and requested_active:
            # No test cases to validate - policy decision: allow inactive only
            log.warning(
                f"Skill '{skill_data.get('name')}' has no test cases; "
                "setting is_active=False"
            )
            is_active = False
        else:
            # No validation requested, use provided is_active
            is_active = requested_active

        # Create with determined is_active
        create_data = {**skill_data, "is_active": is_active}
        return await self.repository.create(create_data)

    async def get_by_id(self, skill_id: str) -> Optional[Skill]:
        """
        Get a skill by its ID.

        Args:
            skill_id: UUID string of the skill

        Returns:
            Skill if found, None otherwise
        """
        return await self.repository.get_by_id(skill_id)

    async def get_by_name(self, name: str) -> Optional[Skill]:
        """
        Get a skill by its name.

        Args:
            name: Name of the skill

        Returns:
            Skill if found, None otherwise
        """
        return await self.repository.get_by_name(name)

    async def list_active(self) -> List[Skill]:
        """
        List all active skills.

        Only returns skills that have passed validation.

        Returns:
            List of active Skill instances
        """
        return await self.repository.list_active()

    async def list_all(self, limit: int = 100, offset: int = 0) -> List[Skill]:
        """
        List all skills with pagination.

        Args:
            limit: Maximum number of skills to return
            offset: Number of skills to skip

        Returns:
            List of Skill instances
        """
        return await self.repository.list_all(limit, offset)

    async def update(
        self,
        skill_id: str,
        skill_data: Dict[str, Any],
        validate: bool = True,
        function_name: str = "execute",
    ) -> Optional[Skill]:
        """
        Update a skill, re-validating if code changed.

        If code is updated and validate=True:
        - Tests are re-run against new code
        - is_active may be set to False if tests fail
        - SkillValidationError is raised if tests fail and is_active was requested

        Args:
            skill_id: UUID string of the skill
            skill_data: Dictionary of fields to update
            validate: Whether to validate tests if code changes
            function_name: Function to call in skill code

        Returns:
            Updated Skill if found, None otherwise

        Raises:
            SkillValidationError: If validation fails and is_active requested
        """
        log.info(f"Updating skill id={skill_id}, validate={validate}")

        existing = await self.repository.get_by_id(skill_id)
        if not existing:
            log.warning(f"Skill not found for update: id={skill_id}")
            return None

        # Determine if code changed
        code_changed = "code" in skill_data and skill_data["code"] != existing.code
        test_cases_changed = "test_cases" in skill_data

        # Get effective code and test cases
        code = skill_data.get("code", existing.code)
        test_cases = skill_data.get("test_cases", existing.test_cases)
        requested_active = skill_data.get("is_active", existing.is_active)

        # Re-validate if code or tests changed
        needs_validation = validate and (code_changed or test_cases_changed)

        if needs_validation and test_cases:
            passed, results = await self.executor.validate_skill(
                code, test_cases, function_name
            )
            if not passed:
                failed_count = sum(1 for r in results if not r.passed)
                if requested_active:
                    raise SkillValidationError(
                        f"Cannot activate skill: {failed_count}/{len(results)} tests failed",
                        test_results=results,
                    )
                # Deactivate if tests now fail
                skill_data["is_active"] = False
                log.warning(
                    f"Skill id={skill_id} deactivated due to failing tests"
                )
        elif needs_validation and not test_cases and requested_active:
            # Code changed but no test cases - cannot activate
            skill_data["is_active"] = False
            log.warning(
                f"Skill id={skill_id} cannot be active without test cases"
            )

        return await self.repository.update(skill_id, skill_data)

    async def activate(
        self,
        skill_id: str,
        function_name: str = "execute",
    ) -> Skill:
        """
        Activate a skill after validating all tests pass.

        This is the DB-06 gate: skills MUST pass all tests to be activated.

        Args:
            skill_id: UUID string of the skill
            function_name: Function to call in skill code

        Returns:
            Activated Skill instance

        Raises:
            ValueError: If skill not found or has no test cases
            SkillValidationError: If any tests fail
        """
        log.info(f"Activating skill id={skill_id}")

        skill = await self.repository.get_by_id(skill_id)
        if not skill:
            raise ValueError(f"Skill not found: {skill_id}")

        if not skill.test_cases:
            raise ValueError(
                f"Cannot activate skill without test cases: {skill_id}"
            )

        # Run validation
        passed, results = await self.executor.validate_skill(
            skill.code, skill.test_cases, function_name
        )

        if not passed:
            failed_count = sum(1 for r in results if not r.passed)
            raise SkillValidationError(
                f"Cannot activate: {failed_count}/{len(results)} tests failed",
                test_results=results,
            )

        # All tests passed - activate
        updated = await self.repository.set_active(skill_id, True)
        log.info(f"Activated skill id={skill_id}")
        return updated

    async def deactivate(self, skill_id: str) -> Optional[Skill]:
        """
        Deactivate a skill.

        Does not require validation - skills can always be deactivated.

        Args:
            skill_id: UUID string of the skill

        Returns:
            Deactivated Skill if found, None otherwise
        """
        log.info(f"Deactivating skill id={skill_id}")
        return await self.repository.set_active(skill_id, False)

    async def run_tests(
        self,
        skill_id: str,
        function_name: str = "execute",
    ) -> Tuple[bool, List[TestResult]]:
        """
        Run tests for a skill without changing its state.

        Useful for checking if a skill can be activated or debugging
        test failures.

        Args:
            skill_id: UUID string of the skill
            function_name: Function to call in skill code

        Returns:
            Tuple of (all_passed, list_of_test_results)

        Raises:
            ValueError: If skill not found
        """
        log.info(f"Running tests for skill id={skill_id}")

        skill = await self.repository.get_by_id(skill_id)
        if not skill:
            raise ValueError(f"Skill not found: {skill_id}")

        if not skill.test_cases:
            log.info(f"Skill id={skill_id} has no test cases")
            return True, []

        passed, results = await self.executor.validate_skill(
            skill.code, skill.test_cases, function_name
        )

        passed_count = sum(1 for r in results if r.passed)
        log.info(
            f"Skill id={skill_id} tests: {passed_count}/{len(results)} passed"
        )

        return passed, results

    async def execute(
        self,
        skill_id: str,
        input_data: Any,
        function_name: str = "execute",
    ) -> Any:
        """
        Execute a skill with given input data.

        Only executes active skills for safety.

        Args:
            skill_id: UUID string of the skill
            input_data: Input data to pass to the skill function
            function_name: Function to call in skill code

        Returns:
            Skill execution output

        Raises:
            ValueError: If skill not found or not active
            SkillExecutionError: If execution fails
        """
        from app.skills.runtime.executor import SkillExecutionError

        log.info(f"Executing skill id={skill_id}")

        skill = await self.repository.get_by_id(skill_id)
        if not skill:
            raise ValueError(f"Skill not found: {skill_id}")

        if not skill.is_active:
            raise ValueError(f"Skill is not active: {skill_id}")

        result = await self.executor.execute_code(
            skill.code, input_data, function_name
        )

        if not result.success:
            raise SkillExecutionError(
                f"Skill execution failed: {result.error}",
                details={"skill_id": skill_id, "input_data": input_data},
            )

        return result.output

    async def delete(self, skill_id: str) -> bool:
        """
        Delete a skill.

        Args:
            skill_id: UUID string of the skill

        Returns:
            True if deleted, False if not found
        """
        return await self.repository.delete(skill_id)
