"""
Container Image Manager - Caches Docker images with pre-installed packages.

Part of Phase 3: Container-Caching & Optimierung

This service manages a cache of Docker images that have common package combinations
pre-installed. When a skill needs to run, we first check if there's a cached image
that already has the required packages, which can reduce startup time from ~30s to <5s.

Architecture:
    ┌─────────────────────────────────────────────────────────────────┐
    │  ContainerImageManager                                          │
    │                                                                 │
    │  find_best_image(pip, apt) → CachedContainerImage or None      │
    │  build_image(pip, apt) → CachedContainerImage                  │
    │  cleanup_old_images(max_age_days) → int                        │
    │                                                                 │
    └─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │  Docker Engine                                                  │
    │                                                                 │
    │  lumari-sandbox:base          (python:3.11-slim)               │
    │  lumari-sandbox:audio-abc123  (+ faster-whisper, ffmpeg)       │
    │  lumari-sandbox:pdf-def456    (+ pypdf, pdfplumber)            │
    │  lumari-sandbox:ocr-ghi789    (+ pytesseract, tesseract-ocr)   │
    │                                                                 │
    └─────────────────────────────────────────────────────────────────┘
"""

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

import docker
from docker.errors import ImageNotFound, BuildError, APIError
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sql.cached_container_models import CachedContainerImage

log = logging.getLogger(__name__)


# Capability type detection based on packages
CAPABILITY_DETECTION = {
    "audio": ["faster-whisper", "openai-whisper", "pydub", "speechrecognition", "pyaudio"],
    "pdf": ["pypdf", "pdfplumber", "PyMuPDF", "pdf2image"],
    "ocr": ["pytesseract", "easyocr", "paddleocr"],
    "excel": ["openpyxl", "xlrd", "pandas"],
    "word": ["python-docx", "docx2txt"],
    "image": ["Pillow", "opencv-python", "imageio"],
    "web": ["requests", "beautifulsoup4", "selenium", "playwright"],
    "video": ["moviepy", "ffmpeg-python", "cv2"],
}


@dataclass
class ImageBuildResult:
    """Result of building a Docker image."""
    success: bool
    image_tag: Optional[str] = None
    size_bytes: Optional[int] = None
    build_time_ms: int = 0
    error: Optional[str] = None


class ContainerImageManager:
    """
    Manages cached Docker images with pre-installed packages.

    This service provides significant performance improvements by:
    1. Caching images with common package combinations
    2. Finding best-matching images for new executions
    3. Building new images when no suitable cache exists
    4. Cleaning up old/unused images

    Example:
        manager = ContainerImageManager(db_session)

        # Find a cached image for audio processing
        image = await manager.find_best_image(
            pip_requirements=["faster-whisper", "pydub"],
            system_packages=["ffmpeg"]
        )

        if image:
            # Use cached image (fast startup)
            container = docker.run(image.image_tag, ...)
        else:
            # Build and cache new image
            result = await manager.build_and_cache_image(
                pip_requirements=["faster-whisper", "pydub"],
                system_packages=["ffmpeg"]
            )
    """

    BASE_IMAGE = "python:3.11-slim"
    IMAGE_PREFIX = "lumari-sandbox"
    MAX_CONCURRENT_BUILDS = 2

    def __init__(
        self,
        db: AsyncSession,
        docker_client: Optional[docker.DockerClient] = None,
    ):
        self.db = db
        self.docker = docker_client or docker.from_env()
        self._build_semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_BUILDS)

    async def find_best_image(
        self,
        pip_requirements: list[str],
        system_packages: list[str],
    ) -> Optional[CachedContainerImage]:
        """
        Find the best matching cached image for the given requirements.

        Returns the image that:
        1. Has all required packages (full coverage)
        2. Has the highest usage count (most proven)
        3. Was used most recently (likely still in Docker cache)

        Returns None if no suitable image exists.
        """
        if not pip_requirements and not system_packages:
            # No requirements = use base image (no cache needed)
            return None

        # Query all ready images
        result = await self.db.execute(
            select(CachedContainerImage).where(
                CachedContainerImage.status == "ready"
            )
        )
        cached_images = result.scalars().all()

        if not cached_images:
            return None

        # Find images that fully cover requirements
        candidates = []
        for image in cached_images:
            if image.matches_requirements(pip_requirements, system_packages):
                candidates.append(image)

        if not candidates:
            log.debug(f"No cached image covers requirements: pip={pip_requirements}, apt={system_packages}")
            return None

        # Sort by: usage_count (desc), last_used_at (desc)
        candidates.sort(
            key=lambda img: (img.usage_count, img.last_used_at or datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True
        )

        best = candidates[0]
        log.info(f"Found cached image: {best.image_tag} (usage={best.usage_count})")

        # Update usage stats
        best.usage_count += 1
        best.last_used_at = datetime.now(timezone.utc)
        await self.db.commit()

        return best

    async def build_and_cache_image(
        self,
        pip_requirements: list[str],
        system_packages: list[str],
        capability_type: Optional[str] = None,
    ) -> ImageBuildResult:
        """
        Build a new Docker image with the specified packages and cache it.

        This is an expensive operation (can take 30-60 seconds) so it should
        only be called when no suitable cached image exists.
        """
        # Detect capability type if not provided
        if not capability_type:
            capability_type = self._detect_capability_type(pip_requirements)

        # Generate unique image tag
        package_hash = self._generate_package_hash(pip_requirements, system_packages)
        image_tag = f"{self.IMAGE_PREFIX}:{capability_type or 'custom'}-{package_hash[:8]}"

        log.info(f"Building image: {image_tag}")
        log.info(f"  pip: {pip_requirements}")
        log.info(f"  apt: {system_packages}")

        # Check if image already exists in Docker
        try:
            existing = self.docker.images.get(image_tag)
            log.info(f"Image already exists in Docker: {image_tag}")

            # Make sure it's in our database
            await self._ensure_db_record(
                image_tag=image_tag,
                pip_packages=pip_requirements,
                system_packages=system_packages,
                capability_type=capability_type,
                size_bytes=existing.attrs.get("Size"),
            )

            return ImageBuildResult(
                success=True,
                image_tag=image_tag,
                size_bytes=existing.attrs.get("Size"),
            )
        except ImageNotFound:
            pass  # Need to build

        # Create DB record with "building" status
        cache_record = CachedContainerImage(
            id=str(uuid.uuid4()),
            image_tag=image_tag,
            pip_packages=pip_requirements,
            system_packages=system_packages,
            capability_type=capability_type,
            status="building",
        )
        self.db.add(cache_record)
        await self.db.commit()

        # Build the image (with semaphore to limit concurrent builds)
        async with self._build_semaphore:
            start_time = datetime.now(timezone.utc)

            try:
                result = await self._build_image(
                    image_tag=image_tag,
                    pip_requirements=pip_requirements,
                    system_packages=system_packages,
                )

                build_time_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

                if result.success:
                    # Update DB record
                    cache_record.status = "ready"
                    cache_record.size_bytes = result.size_bytes
                    cache_record.build_time_ms = build_time_ms
                    cache_record.last_used_at = datetime.now(timezone.utc)
                    await self.db.commit()

                    log.info(f"Image built successfully: {image_tag} ({build_time_ms}ms)")
                else:
                    cache_record.status = "error"
                    cache_record.error_message = result.error
                    await self.db.commit()

                    log.error(f"Image build failed: {result.error}")

                result.build_time_ms = build_time_ms
                return result

            except Exception as e:
                cache_record.status = "error"
                cache_record.error_message = str(e)
                await self.db.commit()

                log.exception(f"Image build failed with exception: {e}")
                return ImageBuildResult(success=False, error=str(e))

    async def _build_image(
        self,
        image_tag: str,
        pip_requirements: list[str],
        system_packages: list[str],
    ) -> ImageBuildResult:
        """Build the Docker image using a Dockerfile."""
        # Generate Dockerfile
        dockerfile = self._generate_dockerfile(pip_requirements, system_packages)

        log.debug(f"Dockerfile:\n{dockerfile}")

        # Build image
        try:
            # Docker SDK build requires a context directory or fileobj
            import io
            import tarfile

            # Create in-memory tar with Dockerfile
            dockerfile_bytes = dockerfile.encode("utf-8")
            tar_buffer = io.BytesIO()

            with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
                dockerfile_info = tarfile.TarInfo(name="Dockerfile")
                dockerfile_info.size = len(dockerfile_bytes)
                tar.addfile(dockerfile_info, io.BytesIO(dockerfile_bytes))

            tar_buffer.seek(0)

            # Build (this is blocking, but we're in an async context with semaphore)
            loop = asyncio.get_event_loop()
            image, build_logs = await loop.run_in_executor(
                None,
                lambda: self.docker.images.build(
                    fileobj=tar_buffer,
                    custom_context=True,
                    tag=image_tag,
                    rm=True,  # Remove intermediate containers
                    forcerm=True,  # Always remove intermediate containers
                    pull=True,  # Pull base image
                )
            )

            # Get image size
            image.reload()
            size_bytes = image.attrs.get("Size", 0)

            return ImageBuildResult(
                success=True,
                image_tag=image_tag,
                size_bytes=size_bytes,
            )

        except BuildError as e:
            error_msg = f"Build failed: {e.msg}"
            for log_line in e.build_log:
                if "error" in str(log_line).lower():
                    error_msg += f"\n{log_line}"
            return ImageBuildResult(success=False, error=error_msg)

        except APIError as e:
            return ImageBuildResult(success=False, error=f"Docker API error: {e}")

    def _generate_dockerfile(
        self,
        pip_requirements: list[str],
        system_packages: list[str],
    ) -> str:
        """Generate a Dockerfile for the given requirements."""
        lines = [
            f"FROM {self.BASE_IMAGE}",
            "",
            "# Set working directory",
            "WORKDIR /workspace",
            "",
        ]

        # Install system packages
        if system_packages:
            packages = " ".join(system_packages)
            lines.extend([
                "# Install system packages",
                "RUN apt-get update && apt-get install -y --no-install-recommends \\",
                f"    {packages} \\",
                "    && rm -rf /var/lib/apt/lists/*",
                "",
            ])

        # Install pip packages
        if pip_requirements:
            packages = " ".join(pip_requirements)
            lines.extend([
                "# Install Python packages",
                f"RUN pip install --no-cache-dir {packages}",
                "",
            ])

        lines.extend([
            "# Default command",
            'CMD ["python"]',
        ])

        return "\n".join(lines)

    def _generate_package_hash(
        self,
        pip_requirements: list[str],
        system_packages: list[str],
    ) -> str:
        """Generate a hash of the package combination for cache keying."""
        # Sort for consistent hashing
        pip_sorted = sorted(pip_requirements or [])
        sys_sorted = sorted(system_packages or [])

        content = f"pip:{','.join(pip_sorted)}|apt:{','.join(sys_sorted)}"
        return hashlib.sha256(content.encode()).hexdigest()

    def _detect_capability_type(self, pip_requirements: list[str]) -> Optional[str]:
        """Detect the capability type based on installed packages."""
        if not pip_requirements:
            return None

        pip_lower = [p.lower() for p in pip_requirements]

        for capability, packages in CAPABILITY_DETECTION.items():
            for pkg in packages:
                if pkg.lower() in pip_lower:
                    return capability

        return None

    async def _ensure_db_record(
        self,
        image_tag: str,
        pip_packages: list[str],
        system_packages: list[str],
        capability_type: Optional[str],
        size_bytes: Optional[int],
    ) -> CachedContainerImage:
        """Ensure a DB record exists for an image."""
        result = await self.db.execute(
            select(CachedContainerImage).where(
                CachedContainerImage.image_tag == image_tag
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.usage_count += 1
            existing.last_used_at = datetime.now(timezone.utc)
            await self.db.commit()
            return existing

        record = CachedContainerImage(
            id=str(uuid.uuid4()),
            image_tag=image_tag,
            pip_packages=pip_packages,
            system_packages=system_packages,
            capability_type=capability_type,
            status="ready",
            size_bytes=size_bytes,
            last_used_at=datetime.now(timezone.utc),
            usage_count=1,
        )
        self.db.add(record)
        await self.db.commit()
        return record

    async def cleanup_old_images(
        self,
        max_age_days: int = 7,
        max_unused_days: int = 3,
        keep_min_images: int = 5,
    ) -> int:
        """
        Clean up old/unused cached images.

        Removes images that:
        - Haven't been used in `max_unused_days`
        - Are older than `max_age_days`
        - Have status="error"

        Always keeps at least `keep_min_images` ready images.

        Returns the number of images removed.
        """
        now = datetime.now(timezone.utc)
        age_cutoff = now - timedelta(days=max_age_days)
        unused_cutoff = now - timedelta(days=max_unused_days)

        # Find images to delete
        result = await self.db.execute(
            select(CachedContainerImage).where(
                (CachedContainerImage.status == "error") |
                (CachedContainerImage.created_at < age_cutoff) |
                (
                    (CachedContainerImage.last_used_at < unused_cutoff) |
                    (CachedContainerImage.last_used_at.is_(None))
                )
            )
        )
        candidates = result.scalars().all()

        # Count ready images
        ready_result = await self.db.execute(
            select(CachedContainerImage).where(
                CachedContainerImage.status == "ready"
            )
        )
        ready_images = ready_result.scalars().all()

        # Don't delete if it would leave us below minimum
        ready_count = len(ready_images)
        ready_to_delete = [c for c in candidates if c.status == "ready"]
        error_to_delete = [c for c in candidates if c.status == "error"]

        # Always delete error images
        to_delete = error_to_delete.copy()

        # Delete ready images only if we have enough
        for img in ready_to_delete:
            if ready_count - len([d for d in to_delete if d.status == "ready"]) > keep_min_images:
                to_delete.append(img)

        removed_count = 0
        for image in to_delete:
            try:
                # Remove from Docker
                try:
                    self.docker.images.remove(image.image_tag, force=True)
                    log.info(f"Removed Docker image: {image.image_tag}")
                except ImageNotFound:
                    pass  # Already gone

                # Remove from DB
                await self.db.delete(image)
                removed_count += 1

            except Exception as e:
                log.warning(f"Failed to remove image {image.image_tag}: {e}")

        await self.db.commit()

        log.info(f"Cleanup complete: removed {removed_count} images")
        return removed_count

    async def get_stats(self) -> dict:
        """Get statistics about cached images."""
        result = await self.db.execute(select(CachedContainerImage))
        images = result.scalars().all()

        ready_images = [i for i in images if i.status == "ready"]
        error_images = [i for i in images if i.status == "error"]
        building_images = [i for i in images if i.status == "building"]

        total_size = sum(i.size_bytes or 0 for i in ready_images)
        total_usage = sum(i.usage_count for i in ready_images)

        # Group by capability
        by_capability = {}
        for img in ready_images:
            cap = img.capability_type or "unknown"
            if cap not in by_capability:
                by_capability[cap] = 0
            by_capability[cap] += 1

        return {
            "total_images": len(images),
            "ready_images": len(ready_images),
            "error_images": len(error_images),
            "building_images": len(building_images),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "total_usage_count": total_usage,
            "by_capability": by_capability,
        }
