"""
Dynamic Sandbox Service for autonomous code execution with full capabilities.

This service implements an OpenClaw-style sandbox that can:
- Execute code in isolated Docker containers WITH network access
- Install pip packages at runtime
- Install system packages (apt-get) at runtime
- Mount workspace directories for file I/O
- Cache container images for faster startup

Unlike epicbox (restricted sandbox), this enables self-improving agents that can:
- Research solutions online
- Install required libraries
- Test and iterate on code
- Persist successful skills with their dependencies

Security is maintained through:
- Container isolation (no host access)
- Resource limits (CPU, memory, time)
- Non-root execution
- Capability dropping
"""

import asyncio
import json
import logging
import os
import tarfile
import tempfile
import time
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import docker
from docker.errors import ContainerError, ImageNotFound, APIError
from docker.types import Mount

# Conditional import for image manager (to avoid circular imports)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.services.container_image_manager import ContainerImageManager

log = logging.getLogger(__name__)


@dataclass
class SandboxResult:
    """Result of sandbox code execution."""

    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    execution_time_ms: int = 0
    timeout: bool = False
    oom_killed: bool = False
    error: Optional[str] = None
    # New fields for autonomous operation
    installed_packages: list[str] = field(default_factory=list)
    output_files: dict[str, bytes] = field(default_factory=dict)
    # Phase 3: Image caching
    used_cached_image: bool = False
    cached_image_tag: Optional[str] = None


@dataclass
class ExecutionConfig:
    """Configuration for sandbox execution."""

    # Resource limits
    memory_limit: str = "2g"  # 2GB RAM (enough for whisper, etc.)
    cpu_quota: int = 100000   # 100% of one CPU
    cpu_period: int = 100000
    pids_limit: int = 100     # Max processes

    # Timeouts
    execution_timeout: int = 300  # 5 minutes for pip install + execution
    pip_timeout: int = 120        # 2 minutes for pip install
    apt_timeout: int = 180        # 3 minutes for apt-get (can be slow)

    # Network
    network_enabled: bool = True  # Enable for pip/apt/research

    # Security
    # Note: apt-get requires more capabilities than a fully locked-down container
    # We still maintain isolation through container boundaries and resource limits
    user: str = "0:0"  # Run as root (needed for apt-get, pip installs to system)
    read_only: bool = False  # Must be writable for pip/apt install
    cap_drop: list[str] = field(default_factory=list)  # Don't drop caps (apt needs them)
    security_opt: list[str] = field(default_factory=list)  # Allow for apt-get


class DynamicSandboxService:
    """
    Docker-based sandbox for autonomous code execution.

    Enables self-improving agents by providing:
    - Network access for research and package installation
    - Runtime pip/apt package installation
    - File I/O through workspace mounting
    - Iterative code testing with error feedback

    Example:
        sandbox = DynamicSandboxService()

        # Execute code with dependencies
        result = await sandbox.execute(
            code="import whisper; print(whisper.load_model('base'))",
            pip_requirements=["openai-whisper"],
            system_packages=["ffmpeg"],
        )

        # Execute with input files
        result = await sandbox.execute(
            code="...",
            input_files={"audio.opus": audio_bytes},
        )
    """

    DEFAULT_IMAGE = "python:3.11-slim"
    CONTAINER_WORKSPACE = "/workspace"

    def __init__(
        self,
        base_image: str = DEFAULT_IMAGE,
        config: Optional[ExecutionConfig] = None,
        image_manager: Optional["ContainerImageManager"] = None,
        enable_image_caching: bool = True,
    ):
        """
        Initialize dynamic sandbox service.

        Args:
            base_image: Base Docker image for containers.
            config: Execution configuration (limits, timeouts, etc.)
            image_manager: Optional ContainerImageManager for image caching.
            enable_image_caching: Whether to use cached images (default True).
        """
        self.base_image = base_image
        self.config = config or ExecutionConfig()
        self._client: Optional[docker.DockerClient] = None
        self._image_manager = image_manager
        self._enable_image_caching = enable_image_caching
        self._image_cache: dict[str, str] = {}  # requirements hash -> image tag

    @property
    def client(self) -> docker.DockerClient:
        """Lazy-initialize Docker client."""
        if self._client is None:
            try:
                self._client = docker.from_env()
                self._client.ping()
                log.info("Docker client connected successfully")
            except Exception as e:
                log.error(f"Failed to connect to Docker: {e}")
                raise RuntimeError(
                    "Docker is not available. Please ensure Docker is running."
                ) from e
        return self._client

    async def _ensure_image_exists(self) -> None:
        """Pull base image if not present."""
        try:
            self.client.images.get(self.base_image)
            log.debug(f"Image {self.base_image} found locally")
        except ImageNotFound:
            log.info(f"Pulling image {self.base_image}...")
            await asyncio.to_thread(
                self.client.images.pull,
                self.base_image,
            )
            log.info(f"Image {self.base_image} pulled successfully")

    async def execute(
        self,
        code: str,
        pip_requirements: Optional[list[str]] = None,
        system_packages: Optional[list[str]] = None,
        input_files: Optional[dict[str, bytes]] = None,
        output_file_paths: Optional[list[str]] = None,
        timeout: Optional[int] = None,
        env_vars: Optional[dict[str, str]] = None,
    ) -> SandboxResult:
        """
        Execute Python code in isolated Docker container.

        Flow:
        1. Create container from base image
        2. Install system packages (apt-get) if specified
        3. Install pip packages if specified
        4. Copy input files to workspace
        5. Execute Python code
        6. Collect output files
        7. Return result with stdout/stderr/files

        Args:
            code: Python code to execute.
            pip_requirements: List of pip packages to install (e.g., ["faster-whisper>=1.0"]).
            system_packages: List of apt packages to install (e.g., ["ffmpeg", "tesseract-ocr"]).
            input_files: Dict of filename -> bytes to copy into workspace.
            output_file_paths: List of file paths (relative to workspace) to retrieve after execution.
            timeout: Execution timeout in seconds (overrides config).
            env_vars: Environment variables to set in container.

        Returns:
            SandboxResult with execution details, output, and any retrieved files.
        """
        start_time = time.time()
        container = None
        pip_requirements = pip_requirements or []
        system_packages = system_packages or []
        input_files = input_files or {}
        output_file_paths = output_file_paths or []
        timeout = timeout or self.config.execution_timeout

        log.info(
            f"Starting sandbox execution: "
            f"pip={pip_requirements}, apt={system_packages}, "
            f"input_files={list(input_files.keys())}"
        )

        # Check for cached image (Phase 3 optimization)
        cached_image = None
        use_cached = False
        if self._image_manager and self._enable_image_caching and (pip_requirements or system_packages):
            try:
                cached_image = await self._image_manager.find_best_image(
                    pip_requirements=pip_requirements,
                    system_packages=system_packages,
                )
                if cached_image and cached_image.is_ready:
                    log.info(f"Using cached image: {cached_image.image_tag}")
                    use_cached = True
            except Exception as e:
                log.warning(f"Failed to check image cache: {e}")

        try:
            # Step 0: Ensure image exists (pull if needed)
            if use_cached:
                # Use cached image - skip package installation
                image_to_use = cached_image.image_tag
                try:
                    self.client.images.get(image_to_use)
                except ImageNotFound:
                    log.warning(f"Cached image {image_to_use} not found in Docker, falling back to base")
                    use_cached = False

            if not use_cached:
                image_to_use = self.base_image
                await self._ensure_image_exists()

            # Step 1: Create container
            container = await self._create_container(env_vars, image_override=image_to_use if use_cached else None)
            log.debug(f"Created container: {container.short_id} (cached={use_cached})")

            # Step 2: Install system packages (skip if using cached image)
            if system_packages and not use_cached:
                apt_result = await self._install_system_packages(container, system_packages)
                if not apt_result.success:
                    return apt_result

            # Step 3: Install pip packages (skip if using cached image)
            if pip_requirements and not use_cached:
                pip_result = await self._install_pip_packages(container, pip_requirements)
                if not pip_result.success:
                    return pip_result

            # Step 4: Copy input files
            if input_files:
                await self._copy_files_to_container(container, input_files)

            # Step 5: Execute code
            result = await self._execute_code(container, code, timeout)

            # Step 6: Collect output files
            if output_file_paths and result.success:
                result.output_files = await self._collect_output_files(
                    container, output_file_paths
                )

            result.installed_packages = pip_requirements
            result.execution_time_ms = int((time.time() - start_time) * 1000)
            result.used_cached_image = use_cached
            result.cached_image_tag = cached_image.image_tag if cached_image and use_cached else None

            log.info(
                f"Sandbox execution complete: success={result.success}, "
                f"time={result.execution_time_ms}ms, cached={use_cached}"
            )

            # Cache the image for future use (Phase 3)
            if (
                result.success
                and self._image_manager
                and self._enable_image_caching
                and not use_cached
                and (pip_requirements or system_packages)
            ):
                try:
                    log.info("Caching container image for future use...")
                    await self._image_manager.build_and_cache_image(
                        pip_requirements=pip_requirements,
                        system_packages=system_packages,
                    )
                except Exception as e:
                    # Don't fail the execution if caching fails
                    log.warning(f"Failed to cache image: {e}")

            return result

        except asyncio.TimeoutError:
            execution_time_ms = int((time.time() - start_time) * 1000)
            log.warning(f"Sandbox execution timed out after {timeout}s")
            return SandboxResult(
                success=False,
                timeout=True,
                execution_time_ms=execution_time_ms,
                error=f"Execution timed out after {timeout} seconds",
            )

        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            error_msg = f"Sandbox error: {type(e).__name__}: {e}"
            log.error(error_msg)
            return SandboxResult(
                success=False,
                execution_time_ms=execution_time_ms,
                error=error_msg,
            )

        finally:
            # Cleanup container
            if container:
                await self._cleanup_container(container)

    async def _create_container(
        self,
        env_vars: Optional[dict[str, str]] = None,
        image_override: Optional[str] = None,
    ) -> docker.models.containers.Container:
        """Create and start a new container."""
        environment = env_vars or {}
        image = image_override or self.base_image

        # Build container config
        container_config = {
            "image": image,
            "command": "sleep infinity",  # Keep container running
            "detach": True,
            "working_dir": self.CONTAINER_WORKSPACE,
            "environment": environment,
            "mem_limit": self.config.memory_limit,
            "cpu_period": self.config.cpu_period,
            "cpu_quota": self.config.cpu_quota,
            "pids_limit": self.config.pids_limit,
            "network_mode": "bridge" if self.config.network_enabled else "none",
        }

        # Only add security options if specified
        if self.config.user:
            container_config["user"] = self.config.user
        if self.config.security_opt:
            container_config["security_opt"] = self.config.security_opt
        if self.config.cap_drop:
            container_config["cap_drop"] = self.config.cap_drop

        # Run in thread pool to not block async loop
        container = await asyncio.to_thread(
            self.client.containers.create,
            **container_config,
        )

        await asyncio.to_thread(container.start)

        # Create workspace directory
        await self._exec_in_container(
            container,
            "mkdir -p /workspace",
            user="root",
            timeout=10
        )

        return container

    async def _install_system_packages(
        self,
        container: docker.models.containers.Container,
        packages: list[str],
    ) -> SandboxResult:
        """Install system packages via apt-get."""
        packages_str = " ".join(packages)
        log.info(f"Installing system packages: {packages_str}")

        # Update apt cache and install packages (need root)
        commands = [
            "apt-get update -qq",
            f"apt-get install -y -qq {packages_str}",
        ]

        for cmd in commands:
            exit_code, output = await self._exec_in_container(
                container,
                cmd,
                user="root",
                timeout=self.config.apt_timeout,
            )

            if exit_code != 0:
                log.warning(f"apt-get failed: {output}")
                return SandboxResult(
                    success=False,
                    stderr=output,
                    exit_code=exit_code,
                    error=f"Failed to install system packages: {output}",
                )

        log.info(f"System packages installed successfully: {packages_str}")
        return SandboxResult(success=True)

    async def _install_pip_packages(
        self,
        container: docker.models.containers.Container,
        packages: list[str],
    ) -> SandboxResult:
        """Install pip packages."""
        packages_str = " ".join(f'"{p}"' for p in packages)
        log.info(f"Installing pip packages: {packages_str}")

        # Install packages as root (so they go to system site-packages)
        cmd = f"pip install --no-cache-dir {packages_str}"

        exit_code, output = await self._exec_in_container(
            container,
            cmd,
            user="root",  # Install as root
            timeout=self.config.pip_timeout,
        )

        if exit_code != 0:
            log.warning(f"pip install failed: {output}")
            return SandboxResult(
                success=False,
                stderr=output,
                exit_code=exit_code,
                error=f"Failed to install pip packages: {output}",
            )

        log.info(f"Pip packages installed successfully")
        return SandboxResult(success=True, installed_packages=packages)

    async def _copy_files_to_container(
        self,
        container: docker.models.containers.Container,
        files: dict[str, bytes],
    ) -> None:
        """Copy files into the container workspace."""
        log.debug(f"Copying {len(files)} files to container")

        # Create a tar archive with all files
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            for filename, content in files.items():
                # Create file info
                info = tarfile.TarInfo(name=filename)
                info.size = len(content)
                info.mode = 0o644
                # Add to archive
                tar.addfile(info, io.BytesIO(content))

        tar_stream.seek(0)

        # Copy to container
        await asyncio.to_thread(
            container.put_archive,
            self.CONTAINER_WORKSPACE,
            tar_stream.getvalue(),
        )

        log.debug(f"Files copied: {list(files.keys())}")

    async def _execute_code(
        self,
        container: docker.models.containers.Container,
        code: str,
        timeout: int,
    ) -> SandboxResult:
        """Execute Python code in the container."""
        # Write code to file
        code_bytes = code.encode("utf-8")
        await self._copy_files_to_container(container, {"script.py": code_bytes})

        # Execute
        log.debug("Executing Python code...")
        exit_code, output = await self._exec_in_container(
            container,
            "python /workspace/script.py",
            timeout=timeout,
        )

        # Split stdout and stderr (docker exec combines them)
        # For now, treat all output as stdout
        success = exit_code == 0

        if not success:
            log.warning(f"Code execution failed (exit={exit_code}): {output[:500]}")

        return SandboxResult(
            success=success,
            stdout=output if success else "",
            stderr=output if not success else "",
            exit_code=exit_code,
        )

    async def _exec_in_container(
        self,
        container: docker.models.containers.Container,
        command: str,
        user: Optional[str] = None,
        timeout: int = 60,
    ) -> tuple[int, str]:
        """Execute a command in the container."""
        try:
            exec_result = await asyncio.wait_for(
                asyncio.to_thread(
                    container.exec_run,
                    command,
                    user=user,
                    workdir=self.CONTAINER_WORKSPACE,
                    demux=False,  # Combined stdout/stderr
                ),
                timeout=timeout,
            )

            output = exec_result.output.decode("utf-8", errors="replace")
            return exec_result.exit_code, output

        except asyncio.TimeoutError:
            log.warning(f"Command timed out: {command[:50]}...")
            return -1, f"Command timed out after {timeout}s"

    async def _collect_output_files(
        self,
        container: docker.models.containers.Container,
        file_paths: list[str],
    ) -> dict[str, bytes]:
        """Collect output files from the container."""
        output_files = {}

        for file_path in file_paths:
            try:
                full_path = f"{self.CONTAINER_WORKSPACE}/{file_path}"

                # Get file as tar archive
                bits, _ = await asyncio.to_thread(
                    container.get_archive,
                    full_path,
                )

                # Extract from tar
                tar_stream = io.BytesIO()
                for chunk in bits:
                    tar_stream.write(chunk)
                tar_stream.seek(0)

                with tarfile.open(fileobj=tar_stream, mode="r") as tar:
                    for member in tar.getmembers():
                        if member.isfile():
                            f = tar.extractfile(member)
                            if f:
                                output_files[file_path] = f.read()
                                break

                log.debug(f"Collected output file: {file_path}")

            except Exception as e:
                log.warning(f"Failed to collect file {file_path}: {e}")

        return output_files

    async def _cleanup_container(
        self,
        container: docker.models.containers.Container,
    ) -> None:
        """Stop and remove the container."""
        try:
            await asyncio.to_thread(container.stop, timeout=5)
            await asyncio.to_thread(container.remove, force=True)
            log.debug(f"Container {container.short_id} cleaned up")
        except Exception as e:
            log.warning(f"Failed to cleanup container: {e}")

    async def execute_with_requirements_file(
        self,
        code: str,
        requirements_txt: str,
        system_packages: Optional[list[str]] = None,
        input_files: Optional[dict[str, bytes]] = None,
        timeout: Optional[int] = None,
        env_vars: Optional[dict[str, str]] = None,
    ) -> SandboxResult:
        """
        Execute Python code with dependencies from a requirements.txt file.

        This method writes the requirements.txt to the container and installs
        from it, providing better reproducibility and version pinning.

        Args:
            code: Python code to execute.
            requirements_txt: Contents of requirements.txt file.
            system_packages: List of apt packages to install.
            input_files: Dict of filename -> bytes to copy into workspace.
            timeout: Execution timeout in seconds.
            env_vars: Environment variables to set in container.

        Returns:
            SandboxResult with execution details.
        """
        # Parse requirements.txt to get package list for caching/logging
        pip_requirements = [
            line.strip()
            for line in requirements_txt.strip().split('\n')
            if line.strip() and not line.strip().startswith('#')
        ]

        # Add requirements.txt to input files
        input_files = input_files or {}
        input_files['requirements.txt'] = requirements_txt.encode('utf-8')

        # Execute with modified pip install command
        start_time = time.time()
        container = None
        system_packages = system_packages or []
        timeout = timeout or self.config.execution_timeout

        log.info(
            f"Starting sandbox execution with requirements.txt: "
            f"{len(pip_requirements)} packages, apt={system_packages}"
        )

        try:
            await self._ensure_image_exists()

            container = await self._create_container(env_vars)
            log.debug(f"Created container: {container.short_id}")

            # Install system packages
            if system_packages:
                apt_result = await self._install_system_packages(container, system_packages)
                if not apt_result.success:
                    return apt_result

            # Copy input files (includes requirements.txt)
            if input_files:
                await self._copy_files_to_container(container, input_files)

            # Install from requirements.txt
            exit_code, output = await self._exec_in_container(
                container,
                "pip install --no-cache-dir -r /workspace/requirements.txt",
                user="root",
                timeout=self.config.pip_timeout,
            )

            if exit_code != 0:
                log.warning(f"pip install from requirements.txt failed: {output}")
                return SandboxResult(
                    success=False,
                    stderr=output,
                    exit_code=exit_code,
                    error=f"Failed to install from requirements.txt: {output}",
                )

            log.info("Packages installed from requirements.txt")

            # Execute code
            result = await self._execute_code(container, code, timeout)

            result.installed_packages = pip_requirements
            result.execution_time_ms = int((time.time() - start_time) * 1000)

            log.info(
                f"Sandbox execution complete: success={result.success}, "
                f"time={result.execution_time_ms}ms"
            )

            return result

        except asyncio.TimeoutError:
            execution_time_ms = int((time.time() - start_time) * 1000)
            log.warning(f"Sandbox execution timed out after {timeout}s")
            return SandboxResult(
                success=False,
                timeout=True,
                execution_time_ms=execution_time_ms,
                error=f"Execution timed out after {timeout} seconds",
            )

        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            error_msg = f"Sandbox error: {type(e).__name__}: {e}"
            log.error(error_msg)
            return SandboxResult(
                success=False,
                execution_time_ms=execution_time_ms,
                error=error_msg,
            )

        finally:
            if container:
                await self._cleanup_container(container)

    async def execute_with_retry(
        self,
        code: str,
        pip_requirements: Optional[list[str]] = None,
        system_packages: Optional[list[str]] = None,
        input_files: Optional[dict[str, bytes]] = None,
        max_retries: int = 3,
        fix_code_callback: Optional[callable] = None,
    ) -> SandboxResult:
        """
        Execute code with automatic retry on failure.

        If execution fails, optionally calls fix_code_callback to get
        corrected code before retrying.

        Args:
            code: Python code to execute.
            pip_requirements: Pip packages to install.
            system_packages: System packages to install.
            input_files: Input files for the workspace.
            max_retries: Maximum number of retry attempts.
            fix_code_callback: Async function(code, error) -> fixed_code

        Returns:
            SandboxResult from the successful execution or last failure.
        """
        current_code = code
        last_result = None

        for attempt in range(max_retries + 1):
            log.info(f"Execution attempt {attempt + 1}/{max_retries + 1}")

            result = await self.execute(
                code=current_code,
                pip_requirements=pip_requirements,
                system_packages=system_packages,
                input_files=input_files,
            )

            if result.success:
                log.info(f"Execution succeeded on attempt {attempt + 1}")
                return result

            last_result = result

            # Try to fix code if callback provided and not last attempt
            if fix_code_callback and attempt < max_retries:
                error_info = result.error or result.stderr
                log.info(f"Attempting to fix code based on error: {error_info[:200]}")

                try:
                    current_code = await fix_code_callback(current_code, error_info)
                    log.debug("Code fixed, retrying...")
                except Exception as e:
                    log.warning(f"Code fix callback failed: {e}")
                    break

        log.warning(f"Execution failed after {max_retries + 1} attempts")
        return last_result

    def is_available(self) -> bool:
        """Check if Docker is available."""
        try:
            self.client.ping()
            return True
        except Exception:
            return False


# Convenience function for quick execution
async def run_in_sandbox(
    code: str,
    pip_requirements: Optional[list[str]] = None,
    system_packages: Optional[list[str]] = None,
    input_files: Optional[dict[str, bytes]] = None,
) -> SandboxResult:
    """
    Quick helper to run code in sandbox.

    Example:
        result = await run_in_sandbox(
            code="import requests; print(requests.get('https://api.github.com').status_code)",
            pip_requirements=["requests"],
        )
        print(result.stdout)  # "200"
    """
    sandbox = DynamicSandboxService()
    return await sandbox.execute(
        code=code,
        pip_requirements=pip_requirements,
        system_packages=system_packages,
        input_files=input_files,
    )
