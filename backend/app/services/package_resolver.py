"""
Package Resolver Service - Dynamic module to pip package resolution.

This service replaces hardcoded import→pip mappings with a dynamic system:
1. Check database cache for known mappings
2. Fall back to hardcoded mappings for reliability
3. Query PyPI API for unknown modules
4. Learn from successful builds
"""

import asyncio
import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.models.sql.skill_build_models import PackageMapping

log = logging.getLogger(__name__)


# Hardcoded fallback mappings for reliability
HARDCODED_MAPPINGS = {
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
    "docx": "python-docx",
    "faster_whisper": "faster-whisper",
    "whisper": "openai-whisper",
    "fitz": "PyMuPDF",
    "pytesseract": "pytesseract",
    "easyocr": "easyocr",
    "pypdf": "pypdf",
    "pdfplumber": "pdfplumber",
    "openpyxl": "openpyxl",
    "pandas": "pandas",
    "numpy": "numpy",
    "requests": "requests",
    "httpx": "httpx",
    "aiohttp": "aiohttp",
    "pydub": "pydub",
    "lxml": "lxml",
    "xlrd": "xlrd",
    "moviepy": "moviepy",
    "speechrecognition": "SpeechRecognition",
    "speech_recognition": "SpeechRecognition",
    "pdf2image": "pdf2image",
    "torch": "torch",
    "tensorflow": "tensorflow",
    "transformers": "transformers",
    "paddleocr": "paddleocr",
    "tabula": "tabula-py",
    "camelot": "camelot-py",
    "spacy": "spacy",
    "nltk": "nltk",
    "psycopg2": "psycopg2-binary",
    "qdrant_client": "qdrant-client",
}

# Standard library modules (don't need pip install)
STDLIB_MODULES = {
    "os", "sys", "json", "re", "time", "datetime", "pathlib", "io",
    "subprocess", "tempfile", "shutil", "glob", "copy", "math",
    "random", "collections", "itertools", "functools", "typing",
    "base64", "hashlib", "uuid", "logging", "warnings", "traceback",
    "asyncio", "concurrent", "threading", "multiprocessing",
    "contextlib", "dataclasses", "enum", "abc", "weakref",
    "string", "textwrap", "struct", "codecs", "unicodedata",
    "difflib", "pprint", "reprlib", "array", "bisect", "heapq",
    "operator", "pickle", "shelve", "dbm", "sqlite3", "csv",
    "configparser", "netrc", "xdrlib", "plistlib", "hmac",
    "secrets", "statistics", "fractions", "decimal", "cmath",
    "numbers", "builtins", "types", "copy", "pprint", "inspect",
    "dis", "pickletools", "formatter", "msilib", "msvcrt",
    "winreg", "winsound", "posix", "pwd", "spwd", "grp", "crypt",
    "termios", "tty", "pty", "fcntl", "pipes", "resource", "nis",
    "syslog", "optparse", "getopt", "argparse", "getpass", "fileinput",
    "stat", "filecmp", "fnmatch", "linecache", "zipfile", "tarfile",
    "gzip", "bz2", "lzma", "zlib", "email", "mailcap", "mailbox",
    "mimetypes", "binascii", "quopri", "uu", "html", "xml", "http",
    "urllib", "ftplib", "poplib", "imaplib", "nntplib", "smtplib",
    "smtpd", "telnetlib", "socketserver", "socket", "ssl", "select",
    "selectors", "signal", "mmap", "venv", "zipimport", "pkgutil",
    "modulefinder", "runpy", "importlib", "platform", "errno", "ctypes",
    "unittest", "doctest", "pdb", "timeit", "trace", "tracemalloc",
}


class PackageResolver:
    """
    Resolves Python module names to pip package names.

    Uses a tiered approach:
    1. Database cache (learned mappings)
    2. Hardcoded fallbacks (reliability)
    3. PyPI API query (discovery)

    Learns from successful builds to improve over time.
    """

    PYPI_SEARCH_URL = "https://pypi.org/pypi/{}/json"
    PYPI_SEARCH_TIMEOUT = 10.0

    def __init__(
        self,
        db: AsyncSession,
        enable_pypi_query: bool = True,
    ):
        """
        Initialize package resolver.

        Args:
            db: Database session for caching
            enable_pypi_query: Whether to query PyPI for unknown packages
        """
        self.db = db
        self.enable_pypi_query = enable_pypi_query
        self._http_client: Optional[httpx.AsyncClient] = None

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Lazy-initialize HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self.PYPI_SEARCH_TIMEOUT)
        return self._http_client

    def is_stdlib(self, module_name: str) -> bool:
        """Check if module is in standard library."""
        return module_name in STDLIB_MODULES

    async def resolve(self, module_name: str) -> Optional[str]:
        """
        Resolve a module name to its pip package name.

        Args:
            module_name: Python import name (e.g., "cv2", "PIL")

        Returns:
            Pip package name (e.g., "opencv-python", "Pillow") or None
        """
        # Skip stdlib modules
        if self.is_stdlib(module_name):
            return None

        # 1. Check database cache
        cached = await self._get_cached_mapping(module_name)
        if cached:
            log.debug(f"Resolved {module_name} -> {cached} (from cache)")
            return cached

        # 2. Check hardcoded mappings
        if module_name in HARDCODED_MAPPINGS:
            package = HARDCODED_MAPPINGS[module_name]
            # Cache it for faster future lookups
            await self._cache_mapping(
                module_name, package, source="hardcoded", confidence=1.0
            )
            log.debug(f"Resolved {module_name} -> {package} (hardcoded)")
            return package

        # 3. Try PyPI query
        if self.enable_pypi_query:
            package = await self._query_pypi(module_name)
            if package:
                await self._cache_mapping(
                    module_name, package, source="pypi", confidence=0.6
                )
                log.debug(f"Resolved {module_name} -> {package} (PyPI)")
                return package

        # 4. Assume module name == package name
        log.debug(f"Assuming {module_name} == {module_name} (fallback)")
        return module_name

    async def resolve_many(self, module_names: list[str]) -> list[str]:
        """
        Resolve multiple module names to pip packages.

        Args:
            module_names: List of Python import names

        Returns:
            List of pip package names (deduplicated, excluding stdlib)
        """
        packages = []
        seen = set()

        for module in module_names:
            package = await self.resolve(module)
            if package and package not in seen:
                packages.append(package)
                seen.add(package)

        return packages

    async def _get_cached_mapping(self, module_name: str) -> Optional[str]:
        """Get mapping from database cache."""
        result = await self.db.execute(
            select(PackageMapping).where(
                PackageMapping.module_name == module_name
            )
        )
        mapping = result.scalar_one_or_none()

        if mapping and mapping.confidence >= 0.3:
            return mapping.package_name

        return None

    async def _cache_mapping(
        self,
        module_name: str,
        package_name: str,
        source: str = "inferred",
        confidence: float = 0.5,
    ) -> None:
        """Cache a mapping in the database."""
        try:
            # Check if exists
            result = await self.db.execute(
                select(PackageMapping).where(
                    PackageMapping.module_name == module_name
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Update if we have higher confidence
                if confidence > existing.confidence:
                    existing.package_name = package_name
                    existing.confidence = confidence
                    existing.source = source
                    existing.updated_at = datetime.now(timezone.utc)
            else:
                # Create new
                mapping = PackageMapping(
                    id=str(uuid.uuid4()),
                    module_name=module_name,
                    package_name=package_name,
                    confidence=confidence,
                    source=source,
                )
                self.db.add(mapping)

            await self.db.commit()

        except Exception as e:
            log.warning(f"Failed to cache mapping {module_name} -> {package_name}: {e}")

    async def _query_pypi(self, module_name: str) -> Optional[str]:
        """Query PyPI API to find package for module."""
        try:
            # First try exact module name
            url = self.PYPI_SEARCH_URL.format(module_name)
            response = await self.http_client.get(url)

            if response.status_code == 200:
                return module_name

            # Try with underscore replaced by hyphen
            alt_name = module_name.replace("_", "-")
            if alt_name != module_name:
                url = self.PYPI_SEARCH_URL.format(alt_name)
                response = await self.http_client.get(url)
                if response.status_code == 200:
                    return alt_name

            # Try python- prefix
            prefixed = f"python-{module_name}"
            url = self.PYPI_SEARCH_URL.format(prefixed)
            response = await self.http_client.get(url)
            if response.status_code == 200:
                return prefixed

            return None

        except Exception as e:
            log.warning(f"PyPI query failed for {module_name}: {e}")
            return None

    async def learn_from_success(
        self,
        module_name: str,
        package_name: str,
    ) -> None:
        """
        Record a successful module->package resolution.

        Call this when a package installation succeeds to improve
        confidence in the mapping.

        Args:
            module_name: The import name that was used
            package_name: The package that was installed
        """
        try:
            result = await self.db.execute(
                select(PackageMapping).where(
                    PackageMapping.module_name == module_name
                )
            )
            mapping = result.scalar_one_or_none()

            if mapping:
                mapping.success_count += 1
                mapping.confidence = min(1.0, mapping.confidence + 0.1)
                mapping.updated_at = datetime.now(timezone.utc)
            else:
                # Create new learned mapping
                mapping = PackageMapping(
                    id=str(uuid.uuid4()),
                    module_name=module_name,
                    package_name=package_name,
                    confidence=0.8,
                    source="learned",
                    success_count=1,
                )
                self.db.add(mapping)

            await self.db.commit()
            log.info(f"Learned successful mapping: {module_name} -> {package_name}")

        except Exception as e:
            log.warning(f"Failed to record success for {module_name}: {e}")

    async def learn_from_failure(
        self,
        module_name: str,
        package_name: str,
    ) -> None:
        """
        Record a failed module->package resolution.

        Call this when a package installation or import fails.

        Args:
            module_name: The import name
            package_name: The package that failed
        """
        try:
            result = await self.db.execute(
                select(PackageMapping).where(
                    PackageMapping.module_name == module_name,
                    PackageMapping.package_name == package_name,
                )
            )
            mapping = result.scalar_one_or_none()

            if mapping:
                mapping.failure_count += 1
                mapping.confidence = max(0.0, mapping.confidence - 0.2)
                mapping.updated_at = datetime.now(timezone.utc)
                await self.db.commit()

                log.info(
                    f"Recorded failure for {module_name} -> {package_name} "
                    f"(confidence now: {mapping.confidence:.2f})"
                )

        except Exception as e:
            log.warning(f"Failed to record failure for {module_name}: {e}")

    async def suggest_alternatives(
        self,
        failed_package: str,
        module_name: Optional[str] = None,
    ) -> list[str]:
        """
        Suggest alternative packages when one fails.

        Args:
            failed_package: The package that failed
            module_name: Optional module name for context

        Returns:
            List of alternative package names to try
        """
        alternatives = []

        # Check if we have alternatives in the database
        if module_name:
            result = await self.db.execute(
                select(PackageMapping).where(
                    PackageMapping.module_name == module_name
                )
            )
            mapping = result.scalar_one_or_none()

            if mapping and mapping.alternatives:
                alternatives.extend(mapping.alternatives)

        # Common alternative patterns
        if not alternatives:
            # Try different naming conventions
            base_name = failed_package.lower().replace("-", "_").replace("python_", "")

            alternatives_to_try = [
                f"py{base_name}",
                f"{base_name}3",
                f"python-{base_name}",
                base_name.replace("_", "-"),
            ]

            for alt in alternatives_to_try:
                if alt != failed_package and alt not in alternatives:
                    alternatives.append(alt)

        return alternatives[:5]  # Limit to 5 suggestions

    async def get_high_confidence_mappings(
        self,
        min_confidence: float = 0.8,
        limit: int = 100,
    ) -> dict[str, str]:
        """
        Get high-confidence mappings for bulk resolution.

        Useful for pre-loading common mappings.
        """
        result = await self.db.execute(
            select(PackageMapping)
            .where(PackageMapping.confidence >= min_confidence)
            .limit(limit)
        )
        mappings = result.scalars().all()

        return {m.module_name: m.package_name for m in mappings}

    async def close(self) -> None:
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
