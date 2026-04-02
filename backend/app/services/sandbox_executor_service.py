"""
Sandbox Executor Service for Docker-isolated code execution via epicbox.

This service implements the second defense layer for generated code:
- Executes code in isolated Docker containers
- Enforces CPU, memory, and time limits
- Disables network access
- Runs as non-root user in read-only filesystem
- Captures pytest test results

Flow:
    CodeValidatorService validates code -> SandboxExecutorService.execute_tests()
    -> Pass: code is safe and tests pass
    -> Fail: return detailed error (validation error, timeout, OOM, test failures)
"""
import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import epicbox

from app.services.code_validator_service import CodeValidatorService, ValidationResult

log = logging.getLogger(__name__)


@dataclass
class SandboxResult:
    """
    Result of sandbox code execution.

    Attributes:
        success: Whether execution completed successfully with all tests passing.
        tests_passed: Number of tests that passed.
        tests_failed: Number of tests that failed.
        stdout: Standard output from execution.
        stderr: Standard error from execution.
        execution_time_ms: Execution time in milliseconds.
        timeout: Whether execution timed out.
        oom_killed: Whether process was killed due to memory limit.
        validation_result: Pre-execution validation result (if failed).
        error: Error message if execution failed.
    """

    success: bool
    tests_passed: int = 0
    tests_failed: int = 0
    stdout: str = ""
    stderr: str = ""
    execution_time_ms: int = 0
    timeout: bool = False
    oom_killed: bool = False
    validation_result: Optional[ValidationResult] = None
    error: Optional[str] = None


class SandboxExecutorService:
    """
    Docker sandbox execution service using epicbox.

    Executes generated code in isolated Docker containers with:
    - CPU time limit (default 5s)
    - Real time limit (default 10s)
    - Memory limit (default 128MB)
    - Network disabled
    - Read-only filesystem

    Example:
        validator = CodeValidatorService()
        sandbox = SandboxExecutorService(validator)

        result = await sandbox.execute_tests(
            code="def add(a, b): return a + b",
            test_code="def test_add(): assert add(1, 2) == 3"
        )
        print(f"Tests passed: {result.success}")
    """

    # Default resource limits (from research)
    DEFAULT_CPUTIME_LIMIT = 5  # seconds
    DEFAULT_REALTIME_LIMIT = 10  # seconds
    DEFAULT_MEMORY_LIMIT = 128  # MB

    def __init__(
        self,
        code_validator: CodeValidatorService,
        docker_image: str = "lumari-sandbox:latest",
        cputime_limit: int = DEFAULT_CPUTIME_LIMIT,
        realtime_limit: int = DEFAULT_REALTIME_LIMIT,
        memory_limit: int = DEFAULT_MEMORY_LIMIT,
    ):
        """
        Initialize sandbox executor.

        Args:
            code_validator: CodeValidatorService for pre-execution validation.
            docker_image: Docker image name for sandbox.
            cputime_limit: CPU time limit in seconds.
            realtime_limit: Wall clock time limit in seconds.
            memory_limit: Memory limit in MB.
        """
        self.validator = code_validator
        self.docker_image = docker_image
        self.limits = {
            "cputime": cputime_limit,
            "realtime": realtime_limit,
            "memory": memory_limit,
            "processes": 1,  # Single process only
        }
        self.log = log

        # Configure epicbox profile
        self._configure_epicbox()

    def _configure_epicbox(self) -> None:
        """Configure epicbox with Python sandbox profile."""
        epicbox.configure(
            profiles=[
                epicbox.Profile(
                    name="python",
                    docker_image=self.docker_image,
                    user="sandbox",
                    read_only=True,
                    network_disabled=True,
                )
            ]
        )
        self.log.info(
            f"Configured epicbox profile: image={self.docker_image}, "
            f"limits={self.limits}"
        )

    async def execute_tests(self, code: str, test_code: str) -> SandboxResult:
        """
        Execute code with tests in isolated Docker sandbox.

        First validates the code via CodeValidatorService, then runs
        pytest in an isolated container with resource limits.

        Args:
            code: Python source code (the skill implementation).
            test_code: Python test code (pytest tests for the skill).

        Returns:
            SandboxResult with execution details and test results.
        """
        start_time = time.time()
        self.log.info("Starting sandbox execution...")

        # Step 1: Validate code before execution
        validation_result = self.validator.validate(code)
        if not validation_result.is_valid:
            self.log.warning(
                f"Code validation failed: {validation_result.blocked_constructs}"
            )
            execution_time_ms = int((time.time() - start_time) * 1000)
            return SandboxResult(
                success=False,
                validation_result=validation_result,
                error=f"Validation failed: {', '.join(validation_result.errors)}",
                execution_time_ms=execution_time_ms,
            )

        # Step 2: Also validate test code
        test_validation_result = self.validator.validate(test_code)
        if not test_validation_result.is_valid:
            self.log.warning(
                f"Test code validation failed: {test_validation_result.blocked_constructs}"
            )
            execution_time_ms = int((time.time() - start_time) * 1000)
            return SandboxResult(
                success=False,
                validation_result=test_validation_result,
                error=f"Test validation failed: {', '.join(test_validation_result.errors)}",
                execution_time_ms=execution_time_ms,
            )

        # Step 3: Prepare files for sandbox
        files = [
            self._create_skill_file(code),
            self._create_test_file(test_code),
        ]

        # Step 4: Execute in sandbox
        command = "python -m pytest test_skill.py -v"

        try:
            self.log.debug(f"Executing in sandbox: {command}")

            # Run epicbox.run() in thread to avoid blocking
            result = await asyncio.to_thread(
                epicbox.run,
                "python",
                command=command,
                files=files,
                limits=self.limits,
            )

            execution_time_ms = int((time.time() - start_time) * 1000)

            # Decode output
            stdout = result.get("stdout", b"").decode("utf-8", errors="replace")
            stderr = result.get("stderr", b"").decode("utf-8", errors="replace")
            timeout = result.get("timeout", False)
            oom_killed = result.get("oom_killed", False)
            exit_code = result.get("exit_code", -1)

            # Log execution details
            self.log.info(
                f"Sandbox execution complete: exit_code={exit_code}, "
                f"timeout={timeout}, oom_killed={oom_killed}, "
                f"time={execution_time_ms}ms"
            )

            # Handle timeout
            if timeout:
                self.log.warning("Sandbox execution timed out")
                return SandboxResult(
                    success=False,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=True,
                    execution_time_ms=execution_time_ms,
                    error="Execution timed out",
                )

            # Handle OOM
            if oom_killed:
                self.log.warning("Sandbox execution killed due to memory limit")
                return SandboxResult(
                    success=False,
                    stdout=stdout,
                    stderr=stderr,
                    oom_killed=True,
                    execution_time_ms=execution_time_ms,
                    error="Process killed: memory limit exceeded",
                )

            # Parse pytest output
            tests_passed, tests_failed = self._parse_pytest_output(stdout)
            success = exit_code == 0 and tests_failed == 0

            if success:
                self.log.info(f"All tests passed: {tests_passed} tests")
            else:
                self.log.warning(
                    f"Tests failed: {tests_passed} passed, {tests_failed} failed"
                )

            return SandboxResult(
                success=success,
                tests_passed=tests_passed,
                tests_failed=tests_failed,
                stdout=stdout,
                stderr=stderr,
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            error_msg = f"Sandbox execution error: {type(e).__name__}: {e}"
            self.log.error(error_msg)
            return SandboxResult(
                success=False,
                execution_time_ms=execution_time_ms,
                error=error_msg,
            )

    def _parse_pytest_output(self, stdout: str) -> tuple[int, int]:
        """
        Parse pytest output to extract passed/failed counts.

        Looks for patterns like:
        - "3 passed"
        - "1 failed"
        - "2 passed, 1 failed"

        Args:
            stdout: Standard output from pytest execution.

        Returns:
            Tuple of (passed_count, failed_count).
        """
        passed = 0
        failed = 0

        # Pattern: "X passed" or "X failed"
        passed_match = re.search(r"(\d+)\s+passed", stdout)
        failed_match = re.search(r"(\d+)\s+failed", stdout)

        if passed_match:
            passed = int(passed_match.group(1))
        if failed_match:
            failed = int(failed_match.group(1))

        self.log.debug(f"Parsed pytest output: {passed} passed, {failed} failed")
        return passed, failed

    def _create_skill_file(self, code: str) -> dict:
        """
        Create skill.py file for sandbox.

        Args:
            code: Python source code for the skill.

        Returns:
            File dict for epicbox with name and content.
        """
        return {"name": "skill.py", "content": code.encode("utf-8")}

    def _create_test_file(self, test_code: str) -> dict:
        """
        Create test_skill.py file for sandbox.

        Args:
            test_code: Python test code (should import from skill.py).

        Returns:
            File dict for epicbox with name and content.
        """
        # Prepend import statement for skill module
        full_test_code = "from skill import *\n\n" + test_code
        return {"name": "test_skill.py", "content": full_test_code.encode("utf-8")}

    async def execute_skill(
        self,
        code: str,
        function_name: str,
        arguments: dict,
        pip_requirements: Optional[list[str]] = None,
        system_packages: Optional[list[str]] = None,
    ) -> SandboxResult:
        """
        Execute a skill function with arguments in isolated Docker sandbox.

        This method is used for runtime skill execution during agent tool calls.
        It validates the code, then executes the specified function with the
        given arguments.

        If pip_requirements or system_packages are provided, this method
        automatically delegates to DynamicSandboxService which has network
        access for package installation.

        If execution fails with ModuleNotFoundError and no packages were specified,
        this method automatically detects the missing module from the code imports
        and retries with DynamicSandboxService.

        Args:
            code: Python source code (the skill implementation).
            function_name: Name of the function to call.
            arguments: Dictionary of arguments to pass to the function.
            pip_requirements: Optional list of pip packages to install.
            system_packages: Optional list of apt packages to install.

        Returns:
            SandboxResult with execution details and function output.
        """
        # If packages are required, delegate to DynamicSandboxService
        if pip_requirements or system_packages:
            return await self._execute_skill_with_packages(
                code=code,
                function_name=function_name,
                arguments=arguments,
                pip_requirements=pip_requirements or [],
                system_packages=system_packages or [],
            )

        # Try epicbox first, then auto-detect missing modules and retry if needed
        result = await self._execute_skill_epicbox(
            code=code,
            function_name=function_name,
            arguments=arguments,
        )

        # Check if failed due to missing module - auto-retry with DynamicSandbox
        if not result.success and self._is_module_not_found_error(result):
            self.log.info("Detected ModuleNotFoundError, auto-detecting dependencies and retrying...")

            # Detect required packages from code imports
            detected_pip, detected_apt = self._detect_required_packages(code)

            if detected_pip or detected_apt:
                self.log.info(f"Auto-detected packages: pip={detected_pip}, apt={detected_apt}")
                return await self._execute_skill_with_packages(
                    code=code,
                    function_name=function_name,
                    arguments=arguments,
                    pip_requirements=detected_pip,
                    system_packages=detected_apt,
                )

        return result

    def _is_module_not_found_error(self, result: SandboxResult) -> bool:
        """Check if the result indicates a ModuleNotFoundError."""
        error_text = (result.error or "") + (result.stderr or "") + (result.stdout or "")
        return "ModuleNotFoundError" in error_text or "No module named" in error_text

    def _detect_required_packages(self, code: str) -> tuple[list[str], list[str]]:
        """
        Detect required pip and apt packages from code imports.

        Returns:
            Tuple of (pip_packages, apt_packages)
        """
        import ast

        # Import name -> pip package mapping
        import_to_pip = {
            'cv2': 'opencv-python',
            'PIL': 'Pillow',
            'sklearn': 'scikit-learn',
            'yaml': 'pyyaml',
            'bs4': 'beautifulsoup4',
            'docx': 'python-docx',
            'faster_whisper': 'faster-whisper',
            'whisper': 'openai-whisper',
            'pydub': 'pydub',
            'pytesseract': 'pytesseract',
            'easyocr': 'easyocr',
            'pypdf': 'pypdf',
            'pdfplumber': 'pdfplumber',
            'fitz': 'PyMuPDF',
            'openpyxl': 'openpyxl',
            'pandas': 'pandas',
            'numpy': 'numpy',
            'requests': 'requests',
            'httpx': 'httpx',
            'aiohttp': 'aiohttp',
            'speechrecognition': 'SpeechRecognition',
            'speech_recognition': 'SpeechRecognition',
        }

        # Packages that need system dependencies
        pip_to_apt = {
            'faster-whisper': ['ffmpeg'],
            'openai-whisper': ['ffmpeg'],
            'pydub': ['ffmpeg'],
            'pytesseract': ['tesseract-ocr'],
            'easyocr': ['libgl1-mesa-glx'],
        }

        # Standard library (skip these)
        stdlib = {
            'os', 'sys', 'json', 're', 'time', 'datetime', 'pathlib', 'io',
            'subprocess', 'tempfile', 'shutil', 'glob', 'copy', 'math',
            'random', 'collections', 'itertools', 'functools', 'typing',
            'base64', 'hashlib', 'uuid', 'logging', 'warnings', 'traceback',
            'asyncio', 'concurrent', 'threading', 'multiprocessing', 'struct',
            'csv', 'string', 'textwrap', 'enum', 'dataclasses', 'contextlib',
        }

        pip_packages = []
        apt_packages = []

        # Extract imports from code
        imports = set()
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name.split('.')[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.add(node.module.split('.')[0])
        except SyntaxError:
            # Fallback to regex
            import_matches = re.findall(r'^import\s+(\w+)', code, re.MULTILINE)
            from_matches = re.findall(r'^from\s+(\w+)', code, re.MULTILINE)
            imports = set(import_matches + from_matches)

        # Convert imports to pip packages
        for imp in imports:
            if imp in stdlib:
                continue

            pip_name = import_to_pip.get(imp, imp)
            if pip_name not in pip_packages:
                pip_packages.append(pip_name)

            # Check if this package needs apt dependencies
            for apt_dep in pip_to_apt.get(pip_name, []):
                if apt_dep not in apt_packages:
                    apt_packages.append(apt_dep)

        return pip_packages, apt_packages

    async def _execute_skill_epicbox(
        self,
        code: str,
        function_name: str,
        arguments: dict,
    ) -> SandboxResult:
        """
        Execute skill in restricted epicbox sandbox (no network).

        This is the original execution path for skills without dependencies.
        """
        start_time = time.time()
        self.log.info(f"Executing skill function '{function_name}' in sandbox...")

        # Step 1: Validate code before execution
        validation_result = self.validator.validate(code)
        if not validation_result.is_valid:
            self.log.warning(
                f"Code validation failed: {validation_result.blocked_constructs}"
            )
            execution_time_ms = int((time.time() - start_time) * 1000)
            return SandboxResult(
                success=False,
                validation_result=validation_result,
                error=f"Validation failed: {', '.join(validation_result.errors)}",
                execution_time_ms=execution_time_ms,
            )

        # Step 2: Create wrapper script that calls the function and prints result
        import json as json_module
        args_json = json_module.dumps(arguments)

        wrapper_code = f'''
import json
import sys

# Import the skill module
from skill import {function_name}

# Parse arguments
args = json.loads('{args_json}')

# Call the function
try:
    result = {function_name}(**args)
    # Output result as JSON for parsing
    print("__RESULT_START__")
    print(json.dumps({{"success": True, "output": result}}, default=str))
    print("__RESULT_END__")
except Exception as e:
    print("__RESULT_START__")
    print(json.dumps({{"success": False, "error": f"{{type(e).__name__}}: {{str(e)}}"}}, default=str))
    print("__RESULT_END__")
'''

        # Step 3: Prepare files for sandbox
        files = [
            self._create_skill_file(code),
            {"name": "run_skill.py", "content": wrapper_code.encode("utf-8")},
        ]

        # Step 4: Execute in sandbox
        command = "python run_skill.py"

        try:
            self.log.debug(f"Executing in sandbox: {command}")

            # Run epicbox.run() in thread to avoid blocking
            result = await asyncio.to_thread(
                epicbox.run,
                "python",
                command=command,
                files=files,
                limits=self.limits,
            )

            execution_time_ms = int((time.time() - start_time) * 1000)

            # Decode output
            stdout = result.get("stdout", b"").decode("utf-8", errors="replace")
            stderr = result.get("stderr", b"").decode("utf-8", errors="replace")
            timeout = result.get("timeout", False)
            oom_killed = result.get("oom_killed", False)
            exit_code = result.get("exit_code", -1)

            # Log execution details
            self.log.info(
                f"Skill execution complete: exit_code={exit_code}, "
                f"timeout={timeout}, oom_killed={oom_killed}, "
                f"time={execution_time_ms}ms"
            )

            # Handle timeout
            if timeout:
                self.log.warning("Skill execution timed out")
                return SandboxResult(
                    success=False,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=True,
                    execution_time_ms=execution_time_ms,
                    error="Execution timed out",
                )

            # Handle OOM
            if oom_killed:
                self.log.warning("Skill execution killed due to memory limit")
                return SandboxResult(
                    success=False,
                    stdout=stdout,
                    stderr=stderr,
                    oom_killed=True,
                    execution_time_ms=execution_time_ms,
                    error="Process killed: memory limit exceeded",
                )

            # Parse output to extract result
            skill_output = self._parse_skill_output(stdout)

            if skill_output is None:
                return SandboxResult(
                    success=False,
                    stdout=stdout,
                    stderr=stderr,
                    execution_time_ms=execution_time_ms,
                    error=f"Failed to parse skill output. stderr: {stderr}",
                )

            return SandboxResult(
                success=skill_output.get("success", False),
                stdout=json_module.dumps(skill_output.get("output")) if skill_output.get("output") else stdout,
                stderr=stderr,
                execution_time_ms=execution_time_ms,
                error=skill_output.get("error"),
            )

        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            error_msg = f"Sandbox execution error: {type(e).__name__}: {e}"
            self.log.error(error_msg)
            return SandboxResult(
                success=False,
                execution_time_ms=execution_time_ms,
                error=error_msg,
            )

    def _parse_skill_output(self, stdout: str) -> Optional[dict]:
        """
        Parse skill execution output to extract the result.

        Looks for JSON between __RESULT_START__ and __RESULT_END__ markers.

        Args:
            stdout: Standard output from skill execution.

        Returns:
            Parsed result dict or None if parsing fails.
        """
        import json as json_module

        try:
            start_marker = "__RESULT_START__"
            end_marker = "__RESULT_END__"

            if start_marker not in stdout or end_marker not in stdout:
                self.log.warning("Result markers not found in output")
                return None

            start_idx = stdout.find(start_marker) + len(start_marker)
            end_idx = stdout.find(end_marker)
            result_str = stdout[start_idx:end_idx].strip()

            return json_module.loads(result_str)
        except (json_module.JSONDecodeError, ValueError) as e:
            self.log.warning(f"Failed to parse skill output: {e}")
            return None

    async def _execute_skill_with_packages(
        self,
        code: str,
        function_name: str,
        arguments: dict,
        pip_requirements: list[str],
        system_packages: list[str],
    ) -> SandboxResult:
        """
        Execute a skill that requires pip/apt packages using DynamicSandboxService.

        This method is called when pip_requirements or system_packages are provided.
        It delegates to DynamicSandboxService which has network access for
        installing dependencies at runtime.

        Args:
            code: Python source code (the skill implementation).
            function_name: Name of the function to call.
            arguments: Dictionary of arguments to pass to the function.
            pip_requirements: List of pip packages to install.
            system_packages: List of apt packages to install.

        Returns:
            SandboxResult with execution details and function output.
        """
        import json as json_module
        start_time = time.time()

        self.log.info(
            f"Executing skill '{function_name}' with packages: "
            f"pip={pip_requirements}, apt={system_packages}"
        )

        # Validate code first (still use our validator)
        validation_result = self.validator.validate(code)
        if not validation_result.is_valid:
            self.log.warning(
                f"Code validation failed: {validation_result.blocked_constructs}"
            )
            execution_time_ms = int((time.time() - start_time) * 1000)
            return SandboxResult(
                success=False,
                validation_result=validation_result,
                error=f"Validation failed: {', '.join(validation_result.errors)}",
                execution_time_ms=execution_time_ms,
            )

        # Create wrapper code that calls the function and captures result
        args_json = json_module.dumps(arguments)

        # Build the wrapper script - includes the skill code and calls the function
        wrapper_code = f'''
{code}

import json
import sys

# Parse arguments
args = json.loads('{args_json}')

# Call the function
try:
    result = {function_name}(**args)
    # Output result as JSON for parsing
    print("__RESULT_START__")
    print(json.dumps({{"success": True, "output": result}}, default=str))
    print("__RESULT_END__")
except Exception as e:
    import traceback
    print("__RESULT_START__")
    print(json.dumps({{"success": False, "error": f"{{type(e).__name__}}: {{str(e)}}", "traceback": traceback.format_exc()}}, default=str))
    print("__RESULT_END__")
'''

        try:
            # Import and use DynamicSandboxService
            from app.services.dynamic_sandbox_service import DynamicSandboxService

            dynamic_sandbox = DynamicSandboxService()
            result = await dynamic_sandbox.execute(
                code=wrapper_code,
                pip_requirements=pip_requirements,
                system_packages=system_packages,
            )

            execution_time_ms = int((time.time() - start_time) * 1000)

            if not result.success:
                self.log.warning(
                    f"Dynamic sandbox execution failed: {result.error or result.stderr}"
                )
                return SandboxResult(
                    success=False,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    execution_time_ms=execution_time_ms,
                    error=result.error or result.stderr,
                )

            # Parse the output to extract result
            output = result.stdout
            skill_output = self._parse_skill_output(output)

            if skill_output is None:
                return SandboxResult(
                    success=False,
                    stdout=output,
                    stderr=result.stderr,
                    execution_time_ms=execution_time_ms,
                    error=f"Failed to parse skill output. Output: {output[:500]}",
                )

            return SandboxResult(
                success=skill_output.get("success", False),
                stdout=json_module.dumps(skill_output.get("output")) if skill_output.get("output") else output,
                stderr=result.stderr,
                execution_time_ms=execution_time_ms,
                error=skill_output.get("error"),
            )

        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            error_msg = f"Dynamic sandbox execution error: {type(e).__name__}: {e}"
            self.log.error(error_msg)
            return SandboxResult(
                success=False,
                execution_time_ms=execution_time_ms,
                error=error_msg,
            )
