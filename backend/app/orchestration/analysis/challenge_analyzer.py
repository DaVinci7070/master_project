"""Challenge analyzer for pre-execution capability assessment."""
import logging
from typing import Callable, Awaitable, Optional

from app.orchestration.topology.loader import TopologyLoader
from app.orchestration.shared_memory.service import SharedMemoryService
from app.orchestration.analysis.capability_matcher import CapabilityMatcher
from app.orchestration.analysis.models import (
    AssessmentContext, CapabilityType, TopologyCapabilities,
    CapabilityExtractionResponse,
)
from app.models.schemas.shared_memory_schemas import SharedMemoryQuery

logger = logging.getLogger(__name__)

# LLM prompt for capability extraction — action-oriented with type classification
CAPABILITY_EXTRACTION_PROMPT = """Analyze this challenge and extract the specific capabilities required to complete it.

## Challenge
{challenge_text}

For each capability, provide:
- action: A concrete verb+object description (e.g. "create SQLite database schema", "execute SQL INSERT queries", "parse CSV file", "analyze meeting transcript")
- type: Either "knowledge" or "execution"

Classification rules:
- "execution" = requires running code, creating files on disk, building software artifacts, computing results programmatically, database operations, data transformations, API calls
  Examples: "build a database schema", "generate Python code", "create a REST API", "compute statistics from CSV", "parse and transform data files", "execute SQL queries"
- "knowledge" = requires reasoning, analyzing text, summarizing, writing reports/documents/protocols, explaining concepts, generating text output
  Examples: "analyze this transcript", "summarize findings", "extract key points", "write a report", "create a daily report from notes", "generate a defect list", "draft a safety protocol", "review code quality"

Important: Creating/generating a TEXT DOCUMENT (report, protocol, list, summary) is KNOWLEDGE — the agent reasons over input and produces text. Creating/building a SOFTWARE ARTIFACT (database, API, code, file system structure) is EXECUTION — the agent must run code.

Return 3-7 capabilities. Respond with JSON only, no markdown:
{{"capabilities": [{{"action": "...", "type": "knowledge|execution"}}]}}"""


class ChallengeAnalyzer:
    """
    Analyzes challenges to extract required capabilities and match against topology.

    This is the core analysis service that:
    1. Extracts required capabilities from challenge text using LLM
    2. Matches capabilities against topology using semantic similarity
    3. Retrieves similar past successes for confidence boosting

    Does NOT determine final confidence level (that's GapDetector's job).
    """

    def __init__(
        self,
        topology_loader: TopologyLoader,
        shared_memory: SharedMemoryService,
        embedding_fn: Optional[Callable[[str], Awaitable[list[float]]]] = None,
        structured_llm_fn: Optional[Callable] = None,
    ):
        """
        Initialize challenge analyzer.

        Args:
            topology_loader: For accessing current topology capabilities
            shared_memory: For retrieving similar past challenges
            embedding_fn: Async function(text) -> embedding vector
            structured_llm_fn: Async function(messages, response_model, **kwargs) -> BaseModel
        """
        self.topology = topology_loader
        self.shared_memory = shared_memory
        self._structured_llm_fn = structured_llm_fn
        self._embedding_fn = embedding_fn

        self.capability_matcher = CapabilityMatcher(
            topology_loader=topology_loader,
            embedding_fn=embedding_fn
        )

    async def analyze(
        self,
        challenge_text: str,
        execution_id: str,
        project_id: str,
        include_cross_project: bool = True
    ) -> AssessmentContext:
        """
        Analyze a challenge and build assessment context.

        Per CONTEXT: Topology is reloaded before each analysis.

        Args:
            challenge_text: The challenge to analyze
            execution_id: Correlation ID for tracking
            project_id: Project for SharedMemory queries
            include_cross_project: Include patterns from other projects

        Returns:
            AssessmentContext with all analysis results
        """
        logger.info(f"Analyzing challenge for execution {execution_id}")

        # 1. Reload topology to ensure fresh capability data (per RESEARCH pitfall 4)
        await self.topology.reload()

        # 2. Extract topology capabilities
        topology_capabilities = await self.capability_matcher.extract_topology_capabilities()
        logger.debug(
            f"Topology: {topology_capabilities.active_agent_count} agents, "
            f"{len(topology_capabilities.all_capabilities)} capabilities"
        )

        # 3. Extract required capabilities from challenge (with type classification)
        required_capabilities, capability_types = await self._extract_required_capabilities(challenge_text)
        logger.info(f"Extracted {len(required_capabilities)} required capabilities")

        # 4. Match capabilities using semantic similarity (passing types through)
        capability_matches = await self.capability_matcher.match_capabilities(
            required_capabilities, topology_capabilities, capability_types
        )

        # 5. Retrieve similar past successes (per CONTEXT: boost confidence)
        similar_successes, confidence_boost = await self._find_similar_successes(
            challenge_text, project_id, include_cross_project
        )

        # 6. Check for schema compatibility issues (per RESEARCH pitfall 5)
        schema_issues = await self._check_schema_compatibility(
            required_capabilities, topology_capabilities
        )

        # Build context for next stage (GapDetector)
        context = AssessmentContext(
            challenge_text=challenge_text,
            execution_id=execution_id,
            project_id=project_id,
            required_capabilities=required_capabilities,
            capability_matches=capability_matches,
            topology_capabilities=topology_capabilities,
            similar_successes=similar_successes,
            confidence_boost=confidence_boost,
            schema_issues=schema_issues
        )

        # Clear matcher cache for next analysis
        self.capability_matcher.clear_cache()

        return context

    async def _extract_required_capabilities(
        self,
        challenge_text: str
    ) -> tuple[list[str], dict[str, CapabilityType]]:
        """
        Extract required capabilities from challenge using LLM.

        Returns:
            (capability_names, capability_types) where capability_types maps
            action string to CapabilityType (KNOWLEDGE or EXECUTION).
        """
        if not self._structured_llm_fn:
            logger.warning("No LLM function configured, using fallback capability extraction")
            return self._fallback_capability_extraction(challenge_text)

        prompt = CAPABILITY_EXTRACTION_PROMPT.format(
            challenge_text=challenge_text[:2000]  # Truncate for context budget
        )

        messages = [
            {"role": "system", "content": "You extract required capabilities from challenges."},
            {"role": "user", "content": prompt}
        ]

        try:
            capability_names = []
            capability_types = {}

            result = await self._structured_llm_fn(
                messages, CapabilityExtractionResponse, temperature=0.0,
            )
            for cap in result.capabilities:
                capability_names.append(cap.action)
                cap_type = (
                    CapabilityType.EXECUTION if cap.type == "execution"
                    else CapabilityType.KNOWLEDGE
                )
                capability_types[cap.action] = cap_type

            logger.info(
                f"LLM extracted {len(capability_names)} capabilities: "
                f"{sum(1 for t in capability_types.values() if t == CapabilityType.EXECUTION)} execution, "
                f"{sum(1 for t in capability_types.values() if t == CapabilityType.KNOWLEDGE)} knowledge"
            )
            logger.debug(f"Capabilities: {list(zip(capability_names, [capability_types[c].value for c in capability_names]))}")

            return capability_names, capability_types

        except Exception as e:
            logger.error(f"LLM capability extraction failed: {e}")
            return self._fallback_capability_extraction(challenge_text)

    def _fallback_capability_extraction(
        self, challenge_text: str
    ) -> tuple[list[str], dict[str, CapabilityType]]:
        """Simple keyword-based fallback when LLM unavailable."""
        keywords = {
            "analyze": ("data analysis", CapabilityType.KNOWLEDGE),
            "generate": ("content generation", CapabilityType.KNOWLEDGE),
            "summarize": ("summarization", CapabilityType.KNOWLEDGE),
            "code": ("code generation", CapabilityType.EXECUTION),
            "build": ("software construction", CapabilityType.EXECUTION),
            "create": ("artifact creation", CapabilityType.EXECUTION),
            "database": ("database operations", CapabilityType.EXECUTION),
            "compute": ("data computation", CapabilityType.EXECUTION),
            "api": ("api integration", CapabilityType.EXECUTION),
            "report": ("report generation", CapabilityType.KNOWLEDGE),
            "test": ("testing", CapabilityType.EXECUTION),
            "deploy": ("deployment", CapabilityType.EXECUTION),
        }

        text_lower = challenge_text.lower()
        names = []
        types = {}
        for keyword, (capability, cap_type) in keywords.items():
            if keyword in text_lower and capability not in names:
                names.append(capability)
                types[capability] = cap_type

        if not names:
            names = ["general processing"]
            types["general processing"] = CapabilityType.KNOWLEDGE

        return names, types

    async def _find_similar_successes(
        self,
        challenge_text: str,
        project_id: str,
        include_cross_project: bool
    ) -> tuple[list[dict], float]:
        """
        Find similar past challenges that succeeded.

        Per CONTEXT: Use success patterns to boost confidence.
        Returns (similar_successes, confidence_boost).
        """
        try:
            # Search current project
            query = SharedMemoryQuery(
                query_text=challenge_text[:500],
                project_id=project_id,
                min_confidence=0.7,  # Only high-confidence past successes
                max_items=10,
                tags=["execution_success", "capability_assessment"]
            )
            current_results = await self.shared_memory.retrieve_context(query)
            current_successes = current_results.get("facts", [])

            # Include cross-project patterns (per CONTEXT decision)
            cross_successes = []
            if include_cross_project:
                cross_results = await self.shared_memory.retrieve_cross_project_context(
                    query, project_id
                )
                cross_successes = cross_results.get("facts", [])

            all_successes = current_successes + cross_successes

            if not all_successes:
                return [], 0.0

            # Calculate confidence boost from top matches
            # Boost = average of top 3 similarity scores * 0.2 (max 0.2 boost)
            top_scores = sorted(
                [s.get("score", 0) for s in all_successes],
                reverse=True
            )[:3]
            confidence_boost = sum(top_scores) / len(top_scores) * 0.2

            logger.debug(
                f"Found {len(all_successes)} similar successes, "
                f"confidence boost: {confidence_boost:.3f}"
            )

            return all_successes, confidence_boost

        except Exception as e:
            logger.error(f"Error finding similar successes: {e}")
            return [], 0.0

    async def _check_schema_compatibility(
        self,
        required_capabilities: list[str],
        topology_capabilities: TopologyCapabilities
    ) -> list[str]:
        """
        Check for potential schema compatibility issues.

        Per RESEARCH pitfall 5: Schema mismatches cause runtime failures
        even when capabilities appear to match.

        This is a lightweight check - full validation happens at execution.
        """
        issues = []

        # Check if topology has dependency issues (from validation)
        if topology_capabilities.has_dependency_issues:
            for issue in topology_capabilities.dependency_issues:
                issues.append(f"Topology dependency issue: {issue}")

        # Note: Full schema validation would require ArtifactSchemaRegistry
        # which is complex. For now, we flag dependency issues as proxies.

        return issues
