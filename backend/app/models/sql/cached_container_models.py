import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, Integer, BigInteger, Text, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.sql.base import Base


class CachedContainerImage(Base):
    """
    Tracks cached Docker images with pre-installed packages.

    These images are built when a skill is successfully developed and can be
    reused for subsequent executions, dramatically reducing startup time.

    Example:
        An image tagged "lumari-sandbox:audio-v1" might have:
        - pip_packages: ["faster-whisper", "pydub"]
        - system_packages: ["ffmpeg"]
        - capability_type: "audio"
    """
    __tablename__ = "cached_container_images"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    image_tag: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    pip_packages: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    system_packages: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    capability_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="ready", nullable=False)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    build_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<CachedContainerImage {self.image_tag} ({self.status})>"

    @property
    def is_ready(self) -> bool:
        """Check if the image is ready to use."""
        return self.status == "ready"

    @staticmethod
    def _normalize_pkg(pkg: str) -> str:
        """Strip version specifiers and normalize: 'faster-whisper>=1.0.0' → 'faster-whisper'"""
        return re.split(r'[><=!~;@\s]', pkg.strip())[0].lower().replace('_', '-')

    def matches_requirements(
        self,
        pip_requirements: list[str],
        system_packages: list[str],
    ) -> bool:
        """
        Check if this image satisfies the given requirements.

        An image matches if it has ALL required packages installed.
        Compares normalized package names (without version specifiers).
        """
        pip_set = {self._normalize_pkg(p) for p in (self.pip_packages or [])}
        sys_set = set(self.system_packages or [])

        required_pip = {self._normalize_pkg(p) for p in (pip_requirements or [])}
        required_sys = set(system_packages or [])

        return required_pip.issubset(pip_set) and required_sys.issubset(sys_set)

    def coverage_score(
        self,
        pip_requirements: list[str],
        system_packages: list[str],
    ) -> float:
        """
        Calculate how well this image covers the requirements.

        Returns a score from 0.0 to 1.0:
        - 1.0 = perfect match (all requirements covered)
        - 0.0 = no overlap
        - 0.5 = half of requirements covered
        """
        pip_set = set(self.pip_packages or [])
        sys_set = set(self.system_packages or [])

        required_pip = set(pip_requirements or [])
        required_sys = set(system_packages or [])

        all_required = required_pip | required_sys
        all_available = pip_set | sys_set

        if not all_required:
            return 1.0

        covered = all_required & all_available
        return len(covered) / len(all_required)
