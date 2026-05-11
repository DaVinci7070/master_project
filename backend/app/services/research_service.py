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
        "pip": ["faster-whisper", "pydub"],
        "apt": ["ffmpeg"],
        "approach": "Use faster-whisper for local transcription (lightweight, no PyTorch needed)",
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
    # Datenbank-Treiber — je nach Kontext waehlen
    "database": {
        "pip": ["psycopg2-binary"], "apt": [],
        "approach": "Use psycopg2-binary for PostgreSQL or sqlite3 (stdlib) for embedded databases. Choose based on the task description.",
    },
    "sqlite": {
        "pip": [], "apt": [], "stdlib": ["sqlite3"],
        "approach": "Use stdlib sqlite3 for local/embedded database operations",
    },
    "csv processing": {
        "pip": [], "apt": [], "stdlib": ["csv"],
        "approach": "Use stdlib csv module for reading/writing CSV files",
    },
    "json processing": {
        "pip": [], "apt": [], "stdlib": ["json"],
        "approach": "Use stdlib json module for JSON parsing and serialization",
    },
    "data computation": {
        "pip": [], "apt": [], "stdlib": ["math", "statistics"],
        "approach": "Use stdlib math/statistics for numerical computations",
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
        self.reset_search_count()

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
        """Perform web-based research with content extraction and LLM summary."""
        context = ResearchContext(capability=capability)

        try:
            # 1. Search for implementations and approaches
            search_results = await self._search_web(
                f"python {capability} implementation example code"
            )

            fetched_sources: list[dict[str, str]] = []

            if search_results:
                context.example_sources.extend(
                    r["url"] for r in search_results[:3]
                )

                # 2. Fetch full page content from top results (parallel)
                async def _fetch_one(result: dict) -> Optional[dict]:
                    content = await self._fetch_page_content(result["url"])
                    if content:
                        return {
                            "url": result["url"],
                            "title": result.get("title", ""),
                            "content": content,
                        }
                    return None

                fetch_tasks = [_fetch_one(r) for r in search_results[:10]]
                fetch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
                for fr in fetch_results:
                    if isinstance(fr, dict):
                        fetched_sources.append(fr)

                # 3. Add search snippets as a source too
                snippet_content = "\n".join(
                    f"- {r['title']}: {r['snippet']}"
                    for r in search_results if r.get("snippet")
                )
                if snippet_content:
                    fetched_sources.append({
                        "url": "DuckDuckGo search snippets",
                        "title": "Search result summaries",
                        "content": snippet_content,
                    })

            # 4. Fetch package docs (existing logic)
            for package in context.pip_packages[:3]:
                doc_snippet = await self._fetch_package_docs(package, capability)
                if doc_snippet:
                    context.code_examples.append(doc_snippet)

            # 5. LLM summarization of all sources into actionable research
            if fetched_sources:
                summary = await self._summarize_research_sources(
                    capability, fetched_sources
                )
                if summary:
                    context.code_examples.insert(0, summary)

        except Exception as e:
            log.warning(f"Web research failed: {e}")

        return context

    # Max searches per skill build to avoid rate-limiting
    MAX_SEARCHES_PER_BUILD = 3
    _search_count: int = 0

    async def _search_web(self, query: str) -> list[dict]:
        """Search the web via DuckDuckGo, return results with snippets.

        Returns list of {url, title, snippet} dicts.
        Rate-limited to MAX_SEARCHES_PER_BUILD per skill build cycle.
        """
        if self._search_count >= self.MAX_SEARCHES_PER_BUILD:
            log.debug(f"Search limit reached ({self.MAX_SEARCHES_PER_BUILD}), skipping")
            return []

        try:
            from ddgs import DDGS

            self._search_count += 1
            raw = await asyncio.to_thread(
                lambda: DDGS().text(query, max_results=5)
            )
            results = [
                {
                    "url": r.get("href", ""),
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                }
                for r in raw
                if r.get("href")
            ]
            log.info(f"Web search for '{query[:60]}' returned {len(results)} results")
            return results

        except ImportError:
            log.warning("ddgs not installed, skipping web search")
            return []
        except Exception as e:
            log.warning(f"Web search failed: {e}")
            return []

    async def _fetch_page_content(self, url: str) -> Optional[str]:
        """Fetch a URL and extract readable content (text + all code blocks).

        Handles Markdown, HTML (including Sphinx/RTD docs), and GitHub raw URLs.
        Returns cleaned text content or None on failure.
        """
        try:
            fetch_url = self._to_raw_url(url)

            response = await self.http_client.get(
                fetch_url,
                follow_redirects=True,
                timeout=15.0,
                headers={"User-Agent": "Lumari-ResearchBot/1.0"},
            )
            if response.status_code != 200:
                return None

            text = response.text

            # If HTML: extract code blocks + clean prose
            if "<html" in text.lower()[:500]:
                text = self._extract_from_html(text)
            else:
                # Markdown or plain text — use as-is
                text = text[:5000]

            return text if len(text) > 50 else None

        except Exception as e:
            log.debug(f"Failed to fetch {url[:60]}: {e}")
            return None

    def _extract_from_html(self, html: str) -> str:
        """Extract readable content + code blocks from HTML documentation pages.

        Handles Sphinx/RTD, MkDocs, and generic HTML. Strips navigation,
        sidebars, headers, and footers to focus on main content.
        """
        import html as html_mod

        # Remove non-content sections first
        cleaned = html
        for tag in ("script", "style", "nav", "header", "footer"):
            cleaned = re.sub(
                rf'<{tag}[^>]*>.*?</{tag}>', '', cleaned, flags=re.DOTALL | re.IGNORECASE
            )
        # Remove sidebar/toc divs (common in Sphinx/RTD/MkDocs)
        cleaned = re.sub(
            r'<div[^>]*class="[^"]*(?:sidebar|sphinxsidebar|toctree|nav-|breadcrumb|headerlink)[^"]*"[^>]*>.*?</div>',
            '', cleaned, flags=re.DOTALL | re.IGNORECASE,
        )

        # Extract code blocks — multiple patterns for different doc generators
        code_patterns = [
            # Sphinx/RTD: <div class="highlight"><pre><span>...</span></pre></div>
            r'<div[^>]*class="[^"]*highlight[^"]*"[^>]*>\s*<pre[^>]*>(.*?)</pre>',
            # Generic: <pre><code>...</code></pre>
            r'<pre[^>]*><code[^>]*>(.*?)</code></pre>',
            # Bare <pre> blocks (some older docs)
            r'<pre[^>]*class="[^"]*(?:literal-block|code-block|sourcecode)[^"]*"[^>]*>(.*?)</pre>',
            # MkDocs: <code class="...">multiline</code> inside <pre>
            r'<pre[^>]*>\s*<code[^>]*>(.*?)</code>\s*</pre>',
        ]

        code_blocks: list[str] = []
        seen_blocks: set[str] = set()
        for pattern in code_patterns:
            for match in re.finditer(pattern, cleaned, re.DOTALL | re.IGNORECASE):
                raw = match.group(1)
                # Strip inner HTML tags (syntax highlighting spans etc.)
                block = re.sub(r'<[^>]+>', '', html_mod.unescape(raw)).strip()
                if block and len(block) > 20 and block not in seen_blocks:
                    seen_blocks.add(block)
                    code_blocks.append(block)

        code_section = ""
        if code_blocks:
            code_section = "\n\n".join(
                f"```\n{b}\n```" for b in code_blocks[:8]
            )

        # Try to isolate main content area (Sphinx, MkDocs, generic)
        main_html = cleaned
        for pattern in [
            r'<div[^>]*class="[^"]*(?:body|document|main-content|md-content|content)[^"]*"[^>]*>(.*)',
            r'<main[^>]*>(.*?)</main>',
            r'<article[^>]*>(.*?)</article>',
        ]:
            m = re.search(pattern, cleaned, re.DOTALL | re.IGNORECASE)
            if m:
                main_html = m.group(1)
                break

        # Strip remaining HTML tags for prose
        prose = re.sub(r'<[^>]+>', ' ', main_html)
        prose = html_mod.unescape(prose)
        prose = re.sub(r'\s+', ' ', prose).strip()[:3000]

        if code_section:
            return f"{prose}\n\n{code_section}"
        return prose

    async def _summarize_research_sources(
        self, capability: str, sources: list[dict[str, str]]
    ) -> str:
        """Use LLM to summarize fetched web sources into actionable research.

        Args:
            capability: What we're trying to build
            sources: List of {url, title, content} dicts

        Returns:
            Condensed research summary with key concepts + code examples
        """
        if not sources:
            return ""

        source_text = ""
        for i, src in enumerate(sources, 1):
            source_text += f"\n\n--- Source {i}: {src['title']} ({src['url']}) ---\n"
            source_text += src["content"][:3000]

        prompt = f"""You are a research assistant for a skill-building system.
We need to build a Python skill for: "{capability}"

Below are web sources found via search. Analyze them and produce a concise research summary:

1. **Key Concepts**: Core patterns, algorithms, or approaches (language-agnostic)
2. **Recommended Libraries**: Python packages with install commands and version info
3. **Implementation Pattern**: Step-by-step how to implement this in Python
4. **Code Examples**: Working Python code snippets (translate from other languages if needed)
5. **Gotchas**: Common pitfalls, edge cases, or important configuration details

Be concise. Focus on what a developer needs to write a working `def execute(input_data: dict) -> dict` function.

{source_text}"""

        try:
            response = await self.llm.chat([{"role": "user", "content": prompt}])
            summary = response.content
            log.info(f"Summarized {len(sources)} sources into {len(summary)} chars")
            return summary[:4000]
        except Exception as e:
            log.warning(f"LLM summarization failed: {e}")
            # Fallback: return raw snippets
            return "\n".join(
                f"# {s['title']}\n{s['content'][:500]}" for s in sources[:3]
            )

    @staticmethod
    def _to_raw_url(url: str) -> str:
        """Convert GitHub URLs to raw content URLs for direct access.

        GitHub HTML pages require JS rendering. Raw URLs return plain text.
        """
        # github.com/owner/repo -> raw README
        match = re.match(r'https?://github\.com/([^/]+/[^/]+)/?$', url)
        if match:
            return f"https://raw.githubusercontent.com/{match.group(1)}/HEAD/README.md"

        # github.com/owner/repo/blob/branch/path -> raw
        match = re.match(
            r'https?://github\.com/([^/]+/[^/]+)/blob/([^/]+)/(.*)', url
        )
        if match:
            return f"https://raw.githubusercontent.com/{match.group(1)}/{match.group(2)}/{match.group(3)}"

        return url

    def reset_search_count(self) -> None:
        """Reset per-build search counter. Call at start of each skill build."""
        self._search_count = 0

    async def _fetch_package_docs(self, package: str, capability: str = "") -> Optional[str]:
        """Fetch full package documentation from PyPI + official docs.

        Hierarchy:
        1. PyPI JSON API → full README with all code examples
        2. Official docs URL from PyPI project_urls → fetch + extract
        3. Targeted doc search for capability-relevant pages
        """
        try:
            # 1. PyPI JSON API — full README as Markdown
            url = self.PYPI_API_URL.format(package)
            response = await self.http_client.get(url)

            if response.status_code != 200:
                return None

            data = response.json()
            info = data.get("info", {})
            description = info.get("description", "")

            content_type = info.get("description_content_type", "") or ""

            # Extract code blocks based on content type
            code_blocks: list[str] = []

            if "rst" in content_type.lower():
                # reStructuredText: .. code-block:: python
                rst_blocks = re.findall(
                    r'\.\.\s+code(?:-block)?::\s*\w*\s*\n((?:\s+.+\n?)+)',
                    description,
                )
                code_blocks.extend(
                    b.replace("\n    ", "\n").strip() for b in rst_blocks
                )

            # Markdown fenced code blocks (works for md and as fallback for rst)
            fenced = re.findall(
                r'```\w*\s*\n(.*?)```',
                description,
                re.DOTALL,
            )
            code_blocks.extend(fenced)

            # Indented code blocks (4 spaces, preceded by blank line)
            indented = re.findall(
                r'\n\n((?:    .+\n?)+)',
                description,
            )
            code_blocks.extend(
                b.replace("\n    ", "\n").lstrip() for b in indented
            )

            # Deduplicate, sort by length, take top 5
            seen: set[str] = set()
            unique_blocks: list[str] = []
            for b in code_blocks:
                stripped = b.strip()
                if stripped and stripped not in seen and len(stripped) > 30:
                    seen.add(stripped)
                    unique_blocks.append(stripped)
            unique_blocks.sort(key=len, reverse=True)

            code_section = "\n\n".join(
                f"```\n{b}\n```" for b in unique_blocks[:5]
            )

            # Package summary (first 500 chars of description without code blocks)
            clean = re.sub(r'```.*?```', '', description, flags=re.DOTALL)
            clean = re.sub(r'\.\.\s+code(?:-block)?::\s*\w*\s*\n(?:\s+.+\n?)+', '', clean)
            summary = clean.strip()[:500]

            result = f"# {package} (PyPI)\n{summary}"
            if code_section:
                result += f"\n\n## Code Examples\n{code_section}"

            # 2. Try to fetch official docs — landing page + targeted search
            project_urls = info.get("project_urls") or {}
            docs_url = (
                project_urls.get("Documentation")
                or project_urls.get("Docs")
                or project_urls.get("Homepage")
            )
            if docs_url:
                docs_content = await self._fetch_page_content(docs_url)
                if docs_content:
                    result += f"\n\n## Official Docs ({docs_url})\n{docs_content[:2000]}"

                # Try common quickstart/getting-started subpages (parallel)
                base = docs_url.rstrip("/")
                quickstart_paths = [
                    "/quickstart", "/getting-started", "/tutorial",
                    "/quickstart.html", "/getting_started.html",
                    "/usage", "/usage.html",
                ]
                qs_tasks = [
                    self._fetch_page_content(base + p) for p in quickstart_paths
                ]
                qs_results = await asyncio.gather(*qs_tasks, return_exceptions=True)
                for i, qs_content in enumerate(qs_results):
                    if isinstance(qs_content, str) and len(qs_content) > 200:
                        qs_url = base + quickstart_paths[i]
                        result += f"\n\n## Getting Started ({qs_url})\n{qs_content[:2000]}"
                        break  # one quickstart page is enough

            # 3. Search docs for capability-specific pages
            docs_extra = await self._search_library_docs(
                package, docs_url, capability
            )
            if docs_extra:
                result += f"\n\n## Relevant Doc Pages\n{docs_extra}"

            return result[:8000]

        except Exception as e:
            log.debug(f"Failed to fetch docs for {package}: {e}")
            return None

    async def _search_library_docs(
        self, package: str, docs_url: Optional[str], capability: str
    ) -> Optional[str]:
        """Search library documentation for capability-relevant pages.

        Strategy:
        1. Try ReadTheDocs search API (most Python libs use it)
        2. Fall back to DuckDuckGo site-scoped search
        3. Fetch top matching pages and extract code examples
        """
        if not capability:
            return None

        results: list[str] = []

        try:
            # 1. ReadTheDocs search API
            rtd_base = None
            if docs_url and "readthedocs" in docs_url:
                rtd_base = docs_url.rstrip("/")
            else:
                # Try common ReadTheDocs URL pattern
                rtd_base = self.READTHEDOCS_URL.format(package.replace("-", "")).rstrip("/")

            if rtd_base:
                search_url = f"{rtd_base}/_/api/v3/search/?q={capability}&page_size=3"
                try:
                    resp = await self.http_client.get(
                        search_url, follow_redirects=True, timeout=10.0,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        for hit in data.get("results", [])[:3]:
                            page_url = hit.get("domain", rtd_base) + hit.get("path", "")
                            title = hit.get("title", "")
                            # Fetch the actual page for code examples
                            page_content = await self._fetch_page_content(page_url)
                            if page_content and len(page_content) > 100:
                                results.append(
                                    f"### {title}\n_Source: {page_url}_\n{page_content[:1500]}"
                                )
                except Exception:
                    pass  # RTD search not available, fall through

            # 2. Fallback: DuckDuckGo site-scoped search
            if not results and docs_url:
                from urllib.parse import urlparse
                domain = urlparse(docs_url).netloc
                if domain:
                    site_results = await self._search_web(
                        f"site:{domain} {package} {capability} example"
                    )
                    for sr in site_results[:2]:
                        page_content = await self._fetch_page_content(sr["url"])
                        if page_content and len(page_content) > 100:
                            results.append(
                                f"### {sr.get('title', '')}\n_Source: {sr['url']}_\n{page_content[:1500]}"
                            )

            # 3. Fallback: general search for package + capability docs
            if not results:
                search_results = await self._search_web(
                    f"{package} python documentation {capability} example"
                )
                for sr in search_results[:2]:
                    page_content = await self._fetch_page_content(sr["url"])
                    if page_content and len(page_content) > 100:
                        results.append(
                            f"### {sr.get('title', '')}\n_Source: {sr['url']}_\n{page_content[:1500]}"
                        )

        except Exception as e:
            log.debug(f"Doc search failed for {package}/{capability}: {e}")

        if not results:
            return None

        return "\n\n".join(results)[:4000]

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
