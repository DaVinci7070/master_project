"""
Research Service - Enhanced capability research with web search and caching.

This service provides comprehensive research for skill development:
1. Web search for implementations and examples
2. Package documentation fetching
3. Similar skill discovery
4. Research caching for efficiency
"""

import asyncio
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.core.llm_client import LLMClient
from app.models.sql.skill_build_models import ResearchCache
from app.models.sql.versioned_models import Skill
from app.models.schemas.skill_build_schemas import ResearchContext

log = logging.getLogger(__name__)


# Capability-specific package hints for common tasks
CAPABILITY_PACKAGE_HINTS = {
    "audio transcription": {
        "pip": ["faster-whisper", "openai-whisper", "speechrecognition", "pydub"],
        "apt": ["ffmpeg"],
        "approach": "Use faster-whisper for local transcription or OpenAI Whisper API",
    },
    "pdf reading": {
        "pip": ["pypdf", "pdfplumber", "PyMuPDF"],
        "apt": [],
        "approach": "pdfplumber for tables, pypdf for text, PyMuPDF for complex layouts",
    },
    "image ocr": {
        "pip": ["pytesseract", "easyocr", "paddleocr"],
        "apt": ["tesseract-ocr"],
        "approach": "easyocr for best accuracy, pytesseract for speed",
    },
    "web scraping": {
        "pip": ["beautifulsoup4", "requests", "lxml", "httpx"],
        "apt": [],
        "approach": "BeautifulSoup for parsing, requests/httpx for fetching",
    },
    "excel reading": {
        "pip": ["openpyxl", "pandas", "xlrd"],
        "apt": [],
        "approach": "openpyxl for xlsx, xlrd for xls, pandas for data analysis",
    },
    "word document reading": {
        "pip": ["python-docx", "docx2txt"],
        "apt": [],
        "approach": "python-docx for full parsing, docx2txt for quick text extraction",
    },
    "video transcription": {
        "pip": ["faster-whisper", "moviepy"],
        "apt": ["ffmpeg"],
        "approach": "Extract audio with moviepy, transcribe with faster-whisper",
    },
    "image processing": {
        "pip": ["opencv-python", "Pillow", "numpy"],
        "apt": [],
        "approach": "OpenCV for complex operations, Pillow for simple transforms",
    },
    "text extraction": {
        "pip": ["beautifulsoup4", "html2text", "markdown"],
        "apt": [],
        "approach": "BeautifulSoup for HTML, specialized parsers for formats",
    },
    "data validation": {
        "pip": ["pydantic", "cerberus", "jsonschema"],
        "apt": [],
        "approach": "Pydantic for type validation, jsonschema for JSON validation",
    },
}


class ResearchService:
    """
    Comprehensive research service for skill development.

    Provides:
    - Web search for implementation approaches
    - Package documentation lookup
    - Similar skill discovery
    - Research caching
    """

    PYPI_API_URL = "https://pypi.org/pypi/{}/json"
    READTHEDOCS_URL = "https://{}.readthedocs.io/en/latest/"
    CACHE_TTL_HOURS = 24

    def __init__(
        self,
        db: AsyncSession,
        llm_client: Optional[LLMClient] = None,
        enable_web_search: bool = True,
        cache_ttl_hours: int = 24,
    ):
        """
        Initialize research service.

        Args:
            db: Database session for caching
            llm_client: LLM for research synthesis
            enable_web_search: Whether to perform web searches
            cache_ttl_hours: How long to cache research results
        """
        self.db = db
        self.llm = llm_client or LLMClient()
        self.enable_web_search = enable_web_search
        self.cache_ttl_hours = cache_ttl_hours
        self._http_client: Optional[httpx.AsyncClient] = None

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Lazy-initialize HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client

    def _hash_capability(self, capability: str) -> str:
        """Create hash of normalized capability for caching."""
        normalized = capability.lower().strip()
        return hashlib.sha256(normalized.encode()).hexdigest()[:32]

    async def research_capability(
        self,
        capability: str,
        hints: Optional[dict] = None,
        force_refresh: bool = False,
    ) -> ResearchContext:
        """
        Research how to implement a capability.

        Args:
            capability: The capability to research
            hints: Optional hints (pip packages, approaches)
            force_refresh: Bypass cache

        Returns:
            ResearchContext with packages, examples, and approach
        """
        log.info(f"Researching capability: {capability}")
        start_time = datetime.now(timezone.utc)

        # Check cache first
        if not force_refresh:
            cached = await self._get_cached_research(capability)
            if cached:
                log.info(f"Using cached research for: {capability}")
                return cached

        # Start with known hints
        context = ResearchContext(
            capability=capability,
            query=f"python {capability} implementation",
        )

        # Add capability-specific hints
        cap_lower = capability.lower()
        for key, hints_data in CAPABILITY_PACKAGE_HINTS.items():
            if key in cap_lower or cap_lower in key:
                context.pip_packages.extend(hints_data.get("pip", []))
                context.system_packages.extend(hints_data.get("apt", []))
                context.implementation_approach = hints_data.get("approach", "")
                context.package_rationale = {
                    pkg: f"Recommended for {key}"
                    for pkg in hints_data.get("pip", [])
                }
                break

        # Extract failure context from hints
        failure_context = ""
        if hints:
            if hints.get("pip"):
                context.pip_packages.extend(hints["pip"])
            if hints.get("apt"):
                context.system_packages.extend(hints["apt"])
            if hints.get("failure_context"):
                failure_context = hints["failure_context"]

        # Web-based research
        if self.enable_web_search:
            web_context = await self._web_research(capability)
            context = self._merge_contexts(context, web_context)

        # Find similar successful skills
        similar = await self._find_similar_skills(capability)
        context.similar_skills = similar

        # LLM synthesis (with failure awareness)
        if not context.code_examples or failure_context:
            llm_context = await self._llm_research(capability, failure_context)
            context = self._merge_contexts(context, llm_context)

        # Deduplicate
        context.pip_packages = list(dict.fromkeys(context.pip_packages))
        context.system_packages = list(dict.fromkeys(context.system_packages))

        # Calculate time
        context.research_time_ms = int(
            (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        )

        # Cache results
        await self._cache_research(capability, context)

        log.info(
            f"Research complete for {capability}: "
            f"pip={context.pip_packages}, examples={len(context.code_examples)}"
        )

        return context

    async def _get_cached_research(self, capability: str) -> Optional[ResearchContext]:
        """Get cached research if valid."""
        cap_hash = self._hash_capability(capability)

        result = await self.db.execute(
            select(ResearchCache).where(
                ResearchCache.capability_hash == cap_hash,
                ResearchCache.is_valid == True,
            )
        )
        cached = result.scalar_one_or_none()

        if not cached:
            return None

        # Check expiry
        if cached.expires_at and cached.expires_at < datetime.now(timezone.utc):
            return None

        # Convert to ResearchContext
        return ResearchContext(
            capability=cached.capability,
            query=f"python {cached.capability} implementation",
            pip_packages=cached.recommended_packages or [],
            system_packages=cached.system_packages or [],
            code_examples=cached.code_examples or [],
            example_sources=cached.sources or [],
            implementation_approach=cached.implementation_notes or "",
            from_cache=True,
        )

    async def _cache_research(self, capability: str, context: ResearchContext) -> None:
        """Cache research results."""
        try:
            cap_hash = self._hash_capability(capability)
            expires_at = datetime.now(timezone.utc) + timedelta(hours=self.cache_ttl_hours)

            # Check if exists
            result = await self.db.execute(
                select(ResearchCache).where(
                    ResearchCache.capability_hash == cap_hash
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Update existing
                existing.recommended_packages = context.pip_packages
                existing.system_packages = context.system_packages
                existing.code_examples = context.code_examples[:5]  # Limit stored examples
                existing.implementation_notes = context.implementation_approach
                existing.sources = context.example_sources
                existing.expires_at = expires_at
                existing.usage_count += 1
            else:
                # Create new
                cache_entry = ResearchCache(
                    id=str(uuid.uuid4()),
                    capability=capability,
                    capability_hash=cap_hash,
                    recommended_packages=context.pip_packages,
                    system_packages=context.system_packages,
                    code_examples=context.code_examples[:5],
                    implementation_notes=context.implementation_approach,
                    sources=context.example_sources,
                    expires_at=expires_at,
                )
                self.db.add(cache_entry)

            await self.db.commit()

        except Exception as e:
            log.warning(f"Failed to cache research: {e}")

    async def _web_research(self, capability: str) -> ResearchContext:
        """Perform web-based research."""
        context = ResearchContext(capability=capability)

        try:
            # Search for Python implementations
            search_results = await self._search_web(
                f"python {capability} implementation example code"
            )
            if search_results:
                context.example_sources.extend(search_results[:3])

            # If we have package suggestions, fetch their docs
            for package in context.pip_packages[:3]:
                doc_snippet = await self._fetch_package_docs(package)
                if doc_snippet:
                    context.code_examples.append(doc_snippet)

        except Exception as e:
            log.warning(f"Web research failed: {e}")

        return context

    async def _search_web(self, query: str) -> list[str]:
        """Search the web for relevant results."""
        # For now, return empty - would integrate with search API
        # Could use: SerpAPI, Google Custom Search, DuckDuckGo, etc.
        return []

    async def _fetch_package_docs(self, package: str) -> Optional[str]:
        """Fetch documentation snippet for a package."""
        try:
            # Try PyPI first for package description
            url = self.PYPI_API_URL.format(package)
            response = await self.http_client.get(url)

            if response.status_code == 200:
                data = response.json()
                info = data.get("info", {})

                # Get description
                description = info.get("description", "")
                if description:
                    # Extract code examples from description
                    code_blocks = re.findall(
                        r'```python\n(.*?)\n```',
                        description,
                        re.DOTALL
                    )
                    if code_blocks:
                        return code_blocks[0][:500]

                    # Or just return first part of description
                    return description[:300]

            return None

        except Exception as e:
            log.debug(f"Failed to fetch docs for {package}: {e}")
            return None

    async def _find_similar_skills(self, capability: str) -> list[dict]:
        """Find similar successful skills in the database."""
        try:
            # Search for skills with similar names/descriptions
            cap_words = set(capability.lower().split())

            result = await self.db.execute(
                select(Skill).where(Skill.is_active == True).limit(50)
            )
            skills = result.scalars().all()

            similar = []
            for skill in skills:
                # Calculate similarity
                skill_words = set(skill.name.lower().replace("_", " ").split())
                if skill.description:
                    skill_words.update(skill.description.lower().split())

                overlap = len(cap_words & skill_words)
                if overlap > 0:
                    score = overlap / max(len(cap_words), 1)
                    if score >= 0.3:
                        similar.append({
                            "id": skill.id,
                            "name": skill.name,
                            "score": score,
                            "packages": skill.skill_metadata.get("pip_requirements", [])
                            if skill.skill_metadata else [],
                        })

            # Sort by score
            similar.sort(key=lambda x: x["score"], reverse=True)
            return similar[:5]

        except Exception as e:
            log.warning(f"Failed to find similar skills: {e}")
            return []

    async def _llm_research(
        self,
        capability: str,
        failure_context: str = "",
    ) -> ResearchContext:
        """Use LLM for research synthesis with failure awareness."""
        context = ResearchContext(capability=capability)

        failure_section = ""
        if failure_context:
            failure_section = f"""
## Previous Failed Attempts (AVOID THESE):
{failure_context}

Based on the failures above, suggest DIFFERENT packages and approaches.
"""

        try:
            prompt = f"""Research how to implement "{capability}" in Python.
{failure_section}
Provide:
1. Best pip packages to use (list 3-5 options)
2. Any system dependencies needed (apt packages)
3. A code example showing basic implementation
4. Implementation approach/notes

Return as JSON:
{{
    "packages": ["package1", "package2"],
    "system_packages": ["apt-pkg1"],
    "code_example": "# Python code here",
    "approach": "Description of approach"
}}"""

            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": "You are a Python expert. Provide practical implementation advice. If previous attempts failed, suggest alternative approaches."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=1000,
            )

            # Parse response
            content = response.content
            json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                    context.pip_packages = data.get("packages", [])
                    context.system_packages = data.get("system_packages", [])
                    if data.get("code_example"):
                        context.code_examples.append(data["code_example"])
                    context.implementation_approach = data.get("approach", "")
                except json.JSONDecodeError:
                    pass

        except Exception as e:
            log.warning(f"LLM research failed: {e}")

        return context

    def _merge_contexts(
        self,
        base: ResearchContext,
        additional: ResearchContext,
    ) -> ResearchContext:
        """Merge two research contexts."""
        base.pip_packages.extend(additional.pip_packages)
        base.system_packages.extend(additional.system_packages)
        base.code_examples.extend(additional.code_examples)
        base.example_sources.extend(additional.example_sources)
        base.potential_issues.extend(additional.potential_issues)
        base.alternative_approaches.extend(additional.alternative_approaches)

        if not base.implementation_approach and additional.implementation_approach:
            base.implementation_approach = additional.implementation_approach

        base.package_rationale.update(additional.package_rationale)

        return base

    async def invalidate_cache(self, capability: str) -> bool:
        """Invalidate cached research for a capability."""
        try:
            cap_hash = self._hash_capability(capability)
            await self.db.execute(
                update(ResearchCache)
                .where(ResearchCache.capability_hash == cap_hash)
                .values(is_valid=False)
            )
            await self.db.commit()
            return True
        except Exception as e:
            log.warning(f"Failed to invalidate cache: {e}")
            return False

    async def update_success_rate(
        self,
        capability: str,
        success: bool,
    ) -> None:
        """Update success rate for cached research."""
        try:
            cap_hash = self._hash_capability(capability)
            result = await self.db.execute(
                select(ResearchCache).where(
                    ResearchCache.capability_hash == cap_hash
                )
            )
            cached = result.scalar_one_or_none()

            if cached:
                cached.usage_count += 1
                # Update rolling success rate
                current_rate = cached.success_rate or 0.0
                # Weighted average with more weight on recent results
                cached.success_rate = (current_rate * 0.7) + (1.0 if success else 0.0) * 0.3
                await self.db.commit()

        except Exception as e:
            log.warning(f"Failed to update success rate: {e}")

    async def close(self) -> None:
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
