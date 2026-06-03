import ast
import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.skills.testing.docker_sandbox import DynamicSandboxService, SandboxResult
from app.skills.testing.container_manager import ContainerImageManager

log = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of skill execution."""
    success: bool
    stdout: str = ""
    stderr: str = ""
    output: Any = None
    error: Optional[str] = None
    execution_time_ms: int = 0
    used_cached_image: bool = False
    skill_auto_built: bool = False


@dataclass
class ExecutionMetrics:
    """Metrics for monitoring."""
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    skills_auto_built: int = 0
    total_execution_time_ms: int = 0

    @property
    def success_rate(self) -> float:
        if self.total_executions == 0:
            return 0.0
        return self.successful_executions / self.total_executions

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        if total == 0:
            return 0.0
        return self.cache_hits / total

    @property
    def avg_execution_time_ms(self) -> float:
        if self.total_executions == 0:
            return 0.0
        return self.total_execution_time_ms / self.total_executions


class AutonomousExecutorService:
    """
    Execution service that combines sandbox execution with autonomous skill building.

    This is the main integration point for the self-improving system:
    - Executes skills in isolated Docker containers
    - Uses cached images when available
    - Can auto-build skills for missing capabilities
    - Tracks metrics for monitoring

    Example:
        executor = AutonomousExecutorService(db_session)

        # Execute a skill
        result = await executor.execute_skill(
            code="def execute(data): return {'result': data['x'] * 2}",
            function_name="execute",
            arguments={"x": 5}
        )

        # Execute with auto-build for unknown capability
        result = await executor.execute_capability(
            capability="audio transcription",
            input_data={"file_path": "/workspace/audio.opus"},
            input_files={"audio.opus": audio_bytes}
        )
    """

    def __init__(
        self,
        db: Optional[AsyncSession] = None,
        sandbox: Optional[DynamicSandboxService] = None,
        image_manager: Optional[ContainerImageManager] = None,
        enable_auto_build: bool = True,
        enable_caching: bool = True,
    ):
        """
        Initialize the autonomous executor.

        Args:
            db: Database session (required for auto-build and caching).
            sandbox: DynamicSandboxService instance (created if not provided).
            image_manager: ContainerImageManager instance (created if db provided).
            enable_auto_build: Whether to auto-build missing skills.
            enable_caching: Whether to use container image caching.
        """
        self.db = db
        self._enable_auto_build = enable_auto_build
        self._enable_caching = enable_caching

        self._image_manager = image_manager
        if enable_caching and db and not image_manager:
            self._image_manager = ContainerImageManager(db=db)

        self._sandbox = sandbox
        if not sandbox:
            self._sandbox = DynamicSandboxService(
                image_manager=self._image_manager if enable_caching else None,
                enable_image_caching=enable_caching,
            )

        self._metrics = ExecutionMetrics()

        self._skill_builder = None

    @property
    def metrics(self) -> ExecutionMetrics:
        """Get current execution metrics."""
        return self._metrics

    async def execute(
        self,
        code: str,
        pip_requirements: Optional[list[str]] = None,
        system_packages: Optional[list[str]] = None,
        timeout: int = 300,
        **kwargs,
    ) -> "SandboxResult":
        """
        Proxy for GenericAgentExecutor compatibility.

        GenericAgentExecutor calls sandbox_executor.execute() with a pre-built
        runner script. This delegates to the underlying DynamicSandboxService.
        """
        return await self._sandbox.execute(
            code=code,
            pip_requirements=pip_requirements,
            system_packages=system_packages,
            timeout=timeout,
        )

    async def execute_skill(
        self,
        code: str,
        function_name: str = "execute",
        arguments: Optional[dict] = None,
        pip_requirements: Optional[list[str]] = None,
        system_packages: Optional[list[str]] = None,
        input_files: Optional[dict[str, bytes]] = None,
        timeout: int = 300,
    ) -> ExecutionResult:
        """
        Execute a skill/function in the sandbox.

        This is the main execution method used by GenericAgentExecutor.
        Includes auto-detection of missing packages and auto-retry on ModuleNotFoundError.

        Args:
            code: Python code containing the function.
            function_name: Name of the function to call.
            arguments: Arguments to pass to the function.
            pip_requirements: Pip packages to install.
            system_packages: System packages to install.
            input_files: Files to provide in the workspace.
            timeout: Execution timeout in seconds.

        Returns:
            ExecutionResult with output or error.
        """
        start_time = time.time()
        self._metrics.total_executions += 1

        if not pip_requirements:
            detected_pip, detected_apt = self._detect_required_packages(code)
            if detected_pip:
                log.info(f"Auto-detected packages: pip={detected_pip}, apt={detected_apt}")
                pip_requirements = detected_pip
                system_packages = list(set((system_packages or []) + detected_apt))

        exec_code = self._build_execution_code(code, function_name, arguments or {})

        result = await self._sandbox.execute(
            code=exec_code,
            pip_requirements=pip_requirements,
            system_packages=system_packages,
            input_files=input_files,
            timeout=timeout,
        )

        if not result.success and self._is_module_not_found_error(result):
            log.info("Detected ModuleNotFoundError, re-analyzing dependencies...")
            detected_pip, detected_apt = self._detect_required_packages(code)

            if detected_pip:
                all_pip = list(set((pip_requirements or []) + detected_pip))
                all_apt = list(set((system_packages or []) + detected_apt))
                log.info(f"Retrying with packages: pip={all_pip}, apt={all_apt}")

                result = await self._sandbox.execute(
                    code=exec_code,
                    pip_requirements=all_pip,
                    system_packages=all_apt,
                    input_files=input_files,
                    timeout=timeout,
                )

        execution_time_ms = int((time.time() - start_time) * 1000)
        self._metrics.total_execution_time_ms += execution_time_ms

        if result.used_cached_image:
            self._metrics.cache_hits += 1
        elif pip_requirements or system_packages:
            self._metrics.cache_misses += 1

        if result.success:
            self._metrics.successful_executions += 1

            output = None
            if result.stdout:
                for line in reversed(result.stdout.strip().split('\n')):
                    line = line.strip()
                    if line.startswith('{') or line.startswith('['):
                        try:
                            output = json.loads(line)
                            break
                        except json.JSONDecodeError:
                            continue
                if output is None:
                    output = result.stdout

            return ExecutionResult(
                success=True,
                stdout=result.stdout,
                output=output,
                execution_time_ms=execution_time_ms,
                used_cached_image=result.used_cached_image,
            )
        else:
            self._metrics.failed_executions += 1
            return ExecutionResult(
                success=False,
                stderr=result.stderr,
                error=result.error or result.stderr,
                execution_time_ms=execution_time_ms,
            )

    async def execute_capability(
        self,
        capability: str,
        input_data: dict,
        input_files: Optional[dict[str, bytes]] = None,
        allow_auto_build: bool = True,
    ) -> ExecutionResult:
        """
        Execute a capability, auto-building the skill if needed.

        This method first looks for an existing skill that provides the capability.
        If not found and auto-build is enabled, it will build one.

        Args:
            capability: Description of the capability (e.g., "audio transcription").
            input_data: Input data for the skill.
            input_files: Optional files to provide.
            allow_auto_build: Whether to auto-build if skill not found.

        Returns:
            ExecutionResult with output or error.
        """
        from app.models.sql.versioned_models import Skill
        from sqlalchemy import select

        skill_name = f"skill_{capability.lower().replace(' ', '_')}"

        if self.db:
            result = await self.db.execute(
                select(Skill).where(
                    (Skill.name == skill_name) & (Skill.is_active == True)
                )
            )
            existing_skill = result.scalar_one_or_none()

            if existing_skill:
                log.info(f"Found existing skill for '{capability}': {existing_skill.name}")

                metadata = existing_skill.skill_metadata or {}
                pip_requirements = metadata.get("pip_requirements", [])
                system_packages = metadata.get("system_packages", [])

                return await self.execute_skill(
                    code=existing_skill.code,
                    function_name="execute",
                    arguments=input_data,
                    pip_requirements=pip_requirements,
                    system_packages=system_packages,
                    input_files=input_files,
                )

        if not allow_auto_build or not self._enable_auto_build:
            return ExecutionResult(
                success=False,
                error=f"No skill found for capability '{capability}' and auto-build is disabled",
            )

        log.info(f"No skill found for '{capability}', attempting to build...")

        build_result = await self._build_skill_for_capability(
            capability=capability,
            test_input=input_data,
            input_files=input_files,
        )

        if not build_result.success:
            return ExecutionResult(
                success=False,
                error=f"Failed to build skill for '{capability}': {build_result.final_error}",
                skill_auto_built=False,
            )

        self._metrics.skills_auto_built += 1

        if build_result.skill:
            metadata = build_result.skill.skill_metadata or {}
            pip_requirements = metadata.get("pip_requirements", [])
            system_packages = metadata.get("system_packages", [])

            result = await self.execute_skill(
                code=build_result.skill.code,
                function_name="execute",
                arguments=input_data,
                pip_requirements=pip_requirements,
                system_packages=system_packages,
                input_files=input_files,
            )
            result.skill_auto_built = True
            return result

        return ExecutionResult(
            success=False,
            error="Skill was built but not returned",
        )

    async def _build_skill_for_capability(
        self,
        capability: str,
        test_input: dict,
        input_files: Optional[dict[str, bytes]] = None,
    ):
        """Build a skill for the given capability using AutonomousSkillBuilder."""
        if not self.db:
            raise RuntimeError("Database session required for skill building")

        if self._skill_builder is None:
            from app.skills.building.autonomous_builder import AutonomousSkillBuilder
            self._skill_builder = AutonomousSkillBuilder(
                db=self.db,
                sandbox=self._sandbox,
            )

        return await self._skill_builder.build_skill(
            capability=capability,
            test_input=test_input,
            input_files=input_files,
        )

    def _build_execution_code(
        self,
        code: str,
        function_name: str,
        arguments: dict,
    ) -> str:
        """Build the complete execution code with function call."""
        args_json = json.dumps(arguments)

        return f'''{code}

# Execute and print result as JSON
if __name__ == "__main__":
    import json
    import inspect
    _input = json.loads({repr(args_json)})

    # Signatur prüfen und passend aufrufen (kwargs vs. positionaler dict)
    _sig = inspect.signature({function_name})
    _params = _sig.parameters
    _has_kwargs = any(p.kind == p.VAR_KEYWORD for p in _params.values())
    _named_params = [n for n, p in _params.items() if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]

    if _has_kwargs or (len(_named_params) > 0 and all(k in _named_params for k in _input)):
        _result = {function_name}(**_input)
    else:
        _result = {function_name}(_input)

    print(json.dumps(_result, default=str))
'''

    def _is_module_not_found_error(self, result: SandboxResult) -> bool:
        """Check if the result indicates a ModuleNotFoundError."""
        error_text = (result.error or "") + (result.stderr or "") + (result.stdout or "")
        return any(pattern in error_text for pattern in [
            "ModuleNotFoundError",
            "No module named",
            "ImportError: cannot import",
        ])

    def _detect_required_packages(self, code: str) -> tuple[list[str], list[str]]:
        """
        Detect required pip and apt packages from code imports.

        Analyzes import statements in the code and maps them to pip package names.
        Also determines system packages (apt) needed for certain pip packages.

        Args:
            code: Python source code to analyze.

        Returns:
            Tuple of (pip_packages, apt_packages).
        """
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
            'torch': 'torch',
            'transformers': 'transformers',
            'librosa': 'librosa',
            'soundfile': 'soundfile',
            'scipy': 'scipy',
            'matplotlib': 'matplotlib',
            'seaborn': 'seaborn',
            'plotly': 'plotly',
        }

        pip_to_apt = {
            'faster-whisper': ['ffmpeg'],
            'openai-whisper': ['ffmpeg'],
            'pydub': ['ffmpeg'],
            'pytesseract': ['tesseract-ocr'],
            'easyocr': ['libgl1-mesa-glx'],
            'opencv-python': ['libgl1-mesa-glx'],
            'librosa': ['ffmpeg', 'libsndfile1'],
            'soundfile': ['libsndfile1'],
        }

        stdlib = {
            'os', 'sys', 'json', 're', 'time', 'datetime', 'pathlib', 'io',
            'subprocess', 'tempfile', 'shutil', 'glob', 'copy', 'math',
            'random', 'collections', 'itertools', 'functools', 'typing',
            'base64', 'hashlib', 'uuid', 'logging', 'warnings', 'traceback',
            'asyncio', 'concurrent', 'threading', 'multiprocessing', 'struct',
            'csv', 'string', 'textwrap', 'enum', 'dataclasses', 'contextlib',
            'abc', 'operator', 'pickle', 'gzip', 'zipfile', 'tarfile',
            'urllib', 'http', 'email', 'html', 'xml', 'codecs', 'locale',
            'argparse', 'configparser', 'secrets', 'statistics', 'decimal',
            'fractions', 'cmath', 'array', 'bisect', 'heapq', 'queue',
            'weakref', 'types', 'inspect', 'dis', 'gc', 'ctypes', 'platform',
        }

        pip_packages = []
        apt_packages = []

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
            import_matches = re.findall(r'^import\s+(\w+)', code, re.MULTILINE)
            from_matches = re.findall(r'^from\s+(\w+)', code, re.MULTILINE)
            imports = set(import_matches + from_matches)

        for imp in imports:
            if imp in stdlib:
                continue

            pip_name = import_to_pip.get(imp, imp)
            if pip_name not in pip_packages:
                pip_packages.append(pip_name)

            for apt_dep in pip_to_apt.get(pip_name, []):
                if apt_dep not in apt_packages:
                    apt_packages.append(apt_dep)

        return pip_packages, apt_packages

    async def cleanup_old_images(
        self,
        max_age_days: int = 7,
        max_unused_days: int = 3,
    ) -> int:
        """Clean up old cached images."""
        if self._image_manager:
            return await self._image_manager.cleanup_old_images(
                max_age_days=max_age_days,
                max_unused_days=max_unused_days,
            )
        return 0

    async def get_cache_stats(self) -> dict:
        """Get container cache statistics."""
        if self._image_manager:
            return await self._image_manager.get_stats()
        return {"caching_enabled": False}

    def get_metrics(self) -> dict:
        """Get execution metrics as dict."""
        return {
            "total_executions": self._metrics.total_executions,
            "successful_executions": self._metrics.successful_executions,
            "failed_executions": self._metrics.failed_executions,
            "success_rate": self._metrics.success_rate,
            "cache_hits": self._metrics.cache_hits,
            "cache_misses": self._metrics.cache_misses,
            "cache_hit_rate": self._metrics.cache_hit_rate,
            "skills_auto_built": self._metrics.skills_auto_built,
            "avg_execution_time_ms": self._metrics.avg_execution_time_ms,
        }


_executor_instance: Optional[AutonomousExecutorService] = None


def get_executor(db: Optional[AsyncSession] = None) -> AutonomousExecutorService:
    """Get or create the singleton executor instance."""
    global _executor_instance

    if _executor_instance is None:
        _executor_instance = AutonomousExecutorService(db=db)
    elif db and _executor_instance.db is None:
        _executor_instance.db = db

    return _executor_instance
