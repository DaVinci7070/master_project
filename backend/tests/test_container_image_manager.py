import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from app.skills.testing.container_manager import (
    ContainerImageManager,
    ImageBuildResult,
    CAPABILITY_DETECTION,
)
from app.models.sql.cached_container_models import CachedContainerImage


class TestCapabilityDetection:
    """Test capability type detection."""

    def test_audio_detection(self):
        """Audio packages should be detected."""
        manager = ContainerImageManager(db=MagicMock())
        assert manager._detect_capability_type(["faster-whisper"]) == "audio"
        assert manager._detect_capability_type(["pydub", "requests"]) == "audio"

    def test_pdf_detection(self):
        """PDF packages should be detected."""
        manager = ContainerImageManager(db=MagicMock())
        assert manager._detect_capability_type(["pypdf"]) == "pdf"
        assert manager._detect_capability_type(["pdfplumber"]) == "pdf"

    def test_ocr_detection(self):
        """OCR packages should be detected."""
        manager = ContainerImageManager(db=MagicMock())
        assert manager._detect_capability_type(["pytesseract"]) == "ocr"
        assert manager._detect_capability_type(["easyocr"]) == "ocr"

    def test_no_detection(self):
        """Unknown packages should return None."""
        manager = ContainerImageManager(db=MagicMock())
        assert manager._detect_capability_type(["unknown-package"]) is None
        assert manager._detect_capability_type([]) is None


class TestPackageHash:
    """Test package hash generation."""

    def test_same_packages_same_hash(self):
        """Same packages should produce same hash."""
        manager = ContainerImageManager(db=MagicMock())
        hash1 = manager._generate_package_hash(["a", "b"], ["x"])
        hash2 = manager._generate_package_hash(["a", "b"], ["x"])
        assert hash1 == hash2

    def test_different_order_same_hash(self):
        """Order shouldn't affect hash."""
        manager = ContainerImageManager(db=MagicMock())
        hash1 = manager._generate_package_hash(["b", "a"], ["x"])
        hash2 = manager._generate_package_hash(["a", "b"], ["x"])
        assert hash1 == hash2

    def test_different_packages_different_hash(self):
        """Different packages should produce different hash."""
        manager = ContainerImageManager(db=MagicMock())
        hash1 = manager._generate_package_hash(["a"], ["x"])
        hash2 = manager._generate_package_hash(["b"], ["x"])
        assert hash1 != hash2


class TestDockerfileGeneration:
    """Test Dockerfile generation."""

    def test_basic_dockerfile(self):
        """Basic Dockerfile should be generated."""
        manager = ContainerImageManager(db=MagicMock())
        dockerfile = manager._generate_dockerfile([], [])

        assert "FROM python:3.11-slim" in dockerfile
        assert "WORKDIR /workspace" in dockerfile

    def test_pip_packages(self):
        """Pip packages should be in Dockerfile."""
        manager = ContainerImageManager(db=MagicMock())
        dockerfile = manager._generate_dockerfile(["requests", "pandas"], [])

        assert "pip install" in dockerfile
        assert "requests pandas" in dockerfile

    def test_apt_packages(self):
        """Apt packages should be in Dockerfile."""
        manager = ContainerImageManager(db=MagicMock())
        dockerfile = manager._generate_dockerfile([], ["ffmpeg", "tesseract-ocr"])

        assert "apt-get install" in dockerfile
        assert "ffmpeg tesseract-ocr" in dockerfile

    def test_both_packages(self):
        """Both pip and apt packages should be in Dockerfile."""
        manager = ContainerImageManager(db=MagicMock())
        dockerfile = manager._generate_dockerfile(["faster-whisper"], ["ffmpeg"])

        assert "apt-get install" in dockerfile
        assert "ffmpeg" in dockerfile
        assert "pip install" in dockerfile
        assert "faster-whisper" in dockerfile


class TestCachedContainerImageModel:
    """Test the CachedContainerImage model methods."""

    def test_matches_requirements_exact(self):
        """Exact match should return True."""
        image = CachedContainerImage(
            id="test",
            image_tag="test:v1",
            pip_packages=["a", "b"],
            system_packages=["x"],
            status="ready",
        )

        assert image.matches_requirements(["a", "b"], ["x"]) is True

    def test_matches_requirements_superset(self):
        """Image with more packages should still match."""
        image = CachedContainerImage(
            id="test",
            image_tag="test:v1",
            pip_packages=["a", "b", "c"],
            system_packages=["x", "y"],
            status="ready",
        )

        assert image.matches_requirements(["a", "b"], ["x"]) is True

    def test_matches_requirements_missing_pip(self):
        """Missing pip package should return False."""
        image = CachedContainerImage(
            id="test",
            image_tag="test:v1",
            pip_packages=["a"],
            system_packages=["x"],
            status="ready",
        )

        assert image.matches_requirements(["a", "b"], ["x"]) is False

    def test_matches_requirements_missing_apt(self):
        """Missing apt package should return False."""
        image = CachedContainerImage(
            id="test",
            image_tag="test:v1",
            pip_packages=["a", "b"],
            system_packages=[],
            status="ready",
        )

        assert image.matches_requirements(["a", "b"], ["x"]) is False

    def test_coverage_score_full(self):
        """Full coverage should return 1.0."""
        image = CachedContainerImage(
            id="test",
            image_tag="test:v1",
            pip_packages=["a", "b"],
            system_packages=["x"],
            status="ready",
        )

        score = image.coverage_score(["a", "b"], ["x"])
        assert score == 1.0

    def test_coverage_score_partial(self):
        """Partial coverage should return fraction."""
        image = CachedContainerImage(
            id="test",
            image_tag="test:v1",
            pip_packages=["a"],
            system_packages=[],
            status="ready",
        )

        score = image.coverage_score(["a", "b"], [])
        assert score == 0.5

    def test_coverage_score_none(self):
        """No coverage should return 0.0."""
        image = CachedContainerImage(
            id="test",
            image_tag="test:v1",
            pip_packages=[],
            system_packages=[],
            status="ready",
        )

        score = image.coverage_score(["a", "b"], ["x"])
        assert score == 0.0


@pytest.mark.asyncio
class TestFindBestImage:
    """Test finding best cached image."""

    async def test_no_requirements_returns_none(self):
        """No requirements should return None (use base image)."""
        mock_db = MagicMock()
        manager = ContainerImageManager(db=mock_db)

        result = await manager.find_best_image([], [])
        assert result is None

    async def test_no_cached_images_returns_none(self):
        """Empty cache should return None."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        manager = ContainerImageManager(db=mock_db)
        result = await manager.find_best_image(["requests"], [])

        assert result is None

    async def test_finds_matching_image(self):
        """Should find image that covers requirements."""
        mock_db = AsyncMock()

        matching_image = CachedContainerImage(
            id="test",
            image_tag="test:v1",
            pip_packages=["requests", "pandas"],
            system_packages=[],
            status="ready",
            usage_count=5,
            last_used_at=datetime.now(timezone.utc),
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [matching_image]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        manager = ContainerImageManager(db=mock_db)
        result = await manager.find_best_image(["requests"], [])

        assert result is not None
        assert result.image_tag == "test:v1"

    async def test_prefers_most_used_image(self):
        """Should prefer image with higher usage count."""
        mock_db = AsyncMock()

        image1 = CachedContainerImage(
            id="test1",
            image_tag="test:v1",
            pip_packages=["requests"],
            system_packages=[],
            status="ready",
            usage_count=10,
            last_used_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        image2 = CachedContainerImage(
            id="test2",
            image_tag="test:v2",
            pip_packages=["requests", "pandas"],
            system_packages=[],
            status="ready",
            usage_count=2,
            last_used_at=datetime.now(timezone.utc),
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [image1, image2]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        manager = ContainerImageManager(db=mock_db)
        result = await manager.find_best_image(["requests"], [])

        assert result is not None
        assert result.image_tag == "test:v1"


@pytest.mark.asyncio
class TestGetStats:
    """Test statistics gathering."""

    async def test_empty_stats(self):
        """Empty cache should return zero stats."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        manager = ContainerImageManager(db=mock_db)
        stats = await manager.get_stats()

        assert stats["total_images"] == 0
        assert stats["ready_images"] == 0
        assert stats["total_size_bytes"] == 0

    async def test_stats_with_images(self):
        """Should calculate correct stats."""
        mock_db = AsyncMock()

        images = [
            CachedContainerImage(
                id="1",
                image_tag="test:v1",
                pip_packages=["requests"],
                system_packages=[],
                status="ready",
                capability_type="web",
                size_bytes=100_000_000,
                usage_count=5,
            ),
            CachedContainerImage(
                id="2",
                image_tag="test:v2",
                pip_packages=["faster-whisper"],
                system_packages=["ffmpeg"],
                status="ready",
                capability_type="audio",
                size_bytes=500_000_000,
                usage_count=10,
            ),
            CachedContainerImage(
                id="3",
                image_tag="test:v3",
                pip_packages=[],
                system_packages=[],
                status="error",
                error_message="Build failed",
            ),
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = images
        mock_db.execute = AsyncMock(return_value=mock_result)

        manager = ContainerImageManager(db=mock_db)
        stats = await manager.get_stats()

        assert stats["total_images"] == 3
        assert stats["ready_images"] == 2
        assert stats["error_images"] == 1
        assert stats["total_size_bytes"] == 600_000_000
        assert stats["total_usage_count"] == 15
        assert stats["by_capability"]["web"] == 1
        assert stats["by_capability"]["audio"] == 1
