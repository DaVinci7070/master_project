"""
Product Owner Service for prioritizing findings and identifying patterns.

This service implements the Product Owner agent from the Developer Team,
which reviews Analyzer findings, identifies patterns across executions,
and prioritizes improvements for downstream agents (Control Agent in Phase 3).
"""
import logging
from collections import Counter
from typing import Optional

from pydantic import ValidationError

from app.core.llm_client import LLMClient, LLMError
from app.models.schemas.analysis_schemas import (
    Finding,
    PriorityList,
    AnalysisFindingResponse,
)
from app.repositories.finding_repository import FindingRepository
from app.prompts.product_owner_prompt import PRODUCT_OWNER_SYSTEM_PROMPT

log = logging.getLogger(__name__)


class ProductOwnerService:
    """
    Product Owner agent: reviews findings, identifies patterns, prioritizes improvements.

    Uses LLM with structured JSON output to produce prioritized action list.
    Part of the Developer Team's post-execution analysis pipeline.

    Flow:
        Analyzer generates findings -> ProductOwnerService.prioritize_findings()
        -> PriorityList with rankings -> Control Agent implements changes

    Example:
        llm_client = LLMClient()
        finding_repo = FindingRepository(session)
        po_service = ProductOwnerService(
            llm_client=llm_client,
            finding_repository=finding_repo
        )

        priority_list = await po_service.prioritize_findings(
            current_findings=analyzer_result.findings,
            execution_id="exec-123",
            agent_id="agent-456"
        )

        print(f"Improvement direction: {priority_list.improvement_direction}")
        for priority in priority_list.priorities:
            print(f"  {priority.priority_rank}: Finding {priority.finding_index}")
    """

    def __init__(
        self,
        llm_client: LLMClient,
        finding_repository: FindingRepository,
    ):
        """
        Initialize the Product Owner service.

        Args:
            llm_client: LLMClient for making LLM inference calls.
            finding_repository: FindingRepository for querying historical findings.
        """
        self.llm = llm_client
        self.finding_repo = finding_repository

    async def prioritize_findings(
        self,
        current_findings: list[Finding],
        execution_id: str,
        agent_id: str,
    ) -> PriorityList:
        """
        Prioritize findings and identify patterns.

        Sends current findings along with historical context to the LLM
        to generate prioritized action items and improvement direction.

        Args:
            current_findings: Findings from the current execution analysis.
            execution_id: UUID of the current execution.
            agent_id: UUID of the agent that executed.

        Returns:
            PriorityList with priority rankings and improvement_direction.
            On any error, returns an empty PriorityList with generic direction.
        """
        log.info(
            f"Prioritizing {len(current_findings)} findings for "
            f"execution={execution_id[:8]}..., agent={agent_id[:8]}..."
        )

        # If no findings, return empty with generic direction
        if not current_findings:
            log.info("No findings to prioritize")
            return PriorityList(
                priorities=[],
                improvement_direction="No issues detected in current execution."
            )

        try:
            # Get historical findings for pattern detection
            pattern_context = await self.get_pattern_context(agent_id)

            # Build the priority prompt
            user_prompt = self._build_priority_prompt(
                current_findings=current_findings,
                pattern_context=pattern_context,
                execution_id=execution_id,
            )

            # Build JSON schema for structured output
            json_schema = self._build_json_schema()

            # Call LLM with structured output
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": PRODUCT_OWNER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,  # Slightly creative for synthesis
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "priority_list",
                        "strict": True,
                        "schema": json_schema,
                    },
                },
            )

            log.debug(f"LLM response: {response.content[:200]}...")

            # Parse and validate the response
            result = PriorityList.model_validate_json(response.content)

            log.info(
                f"Prioritization complete: {len(result.priorities)} items prioritized, "
                f"direction='{result.improvement_direction[:50]}...'"
            )

            return result

        except LLMError as e:
            log.warning(
                f"LLM error during prioritization for execution={execution_id[:8]}: {e}"
            )
            return PriorityList(
                priorities=[],
                improvement_direction="Unable to prioritize - review findings manually."
            )

        except ValidationError as e:
            log.warning(
                f"Validation error parsing priorities for execution={execution_id[:8]}: {e}"
            )
            return PriorityList(
                priorities=[],
                improvement_direction="Unable to parse prioritization result."
            )

        except Exception as e:
            log.error(
                f"Unexpected error prioritizing findings for execution={execution_id[:8]}: {e}",
                exc_info=True,
            )
            return PriorityList(
                priorities=[],
                improvement_direction="Prioritization failed due to unexpected error."
            )

    async def get_pattern_context(
        self,
        agent_id: str,
        limit: int = 10,
    ) -> list[AnalysisFindingResponse]:
        """
        Get recent findings for pattern detection.

        Queries the FindingRepository for historical findings from this agent
        to identify recurring patterns across executions.

        Args:
            agent_id: UUID of the agent.
            limit: Maximum number of historical findings to retrieve.

        Returns:
            List of AnalysisFindingResponse for pattern context.
        """
        log.debug(f"Getting pattern context for agent={agent_id[:8]}..., limit={limit}")

        try:
            findings = await self.finding_repo.get_by_agent_id(agent_id, limit=limit)

            # Convert to response schema
            responses = [
                AnalysisFindingResponse.model_validate(finding)
                for finding in findings
            ]

            log.debug(f"Retrieved {len(responses)} historical findings for pattern context")
            return responses

        except Exception as e:
            log.warning(f"Error getting pattern context for agent={agent_id[:8]}: {e}")
            return []

    def _build_priority_prompt(
        self,
        current_findings: list[Finding],
        pattern_context: list[AnalysisFindingResponse],
        execution_id: str,
    ) -> str:
        """
        Build the user prompt with current findings and historical context.

        Formats findings for the LLM to analyze and prioritize, including
        pattern statistics from recent executions.

        Args:
            current_findings: Findings from current execution.
            pattern_context: Historical findings for pattern detection.
            execution_id: UUID of current execution.

        Returns:
            Formatted prompt string for the LLM.
        """
        lines = ["## Current Findings to Prioritize", ""]

        # List current findings with indices
        for i, finding in enumerate(current_findings):
            lines.append(f"### Finding {i}")
            lines.append(f"- **Category**: {finding.category}")
            lines.append(f"- **Severity**: {finding.severity}")
            lines.append(f"- **Evidence**: {finding.evidence}")
            lines.append(f"- **Suggested Fix**: {finding.suggested_fix}")
            lines.append("")

        # Add pattern context
        lines.append("## Historical Context (Recent Findings)")
        lines.append("")

        if not pattern_context:
            lines.append("No historical findings available for pattern detection.")
        else:
            # Compute summary statistics
            severity_counts = Counter(f.severity for f in pattern_context)
            category_counts = Counter(f.category for f in pattern_context)

            lines.append(
                f"Last {len(pattern_context)} findings: "
                f"{severity_counts.get('critical', 0)} critical, "
                f"{severity_counts.get('warning', 0)} warning, "
                f"{severity_counts.get('info', 0)} info"
            )
            lines.append("")

            # Show category breakdown
            lines.append("Category breakdown:")
            for category, count in category_counts.most_common():
                lines.append(f"  - {category}: {count}")
            lines.append("")

            # Identify potential patterns (repeated categories or suggested fixes)
            repeated_categories = [cat for cat, count in category_counts.items() if count >= 2]
            if repeated_categories:
                lines.append("**Potential patterns detected:**")
                for cat in repeated_categories:
                    lines.append(f"  - '{cat}' issues appearing {category_counts[cat]} times")
                lines.append("")

            # List recent findings briefly
            lines.append("Recent findings (most recent first):")
            for finding in pattern_context[:5]:  # Limit to 5 for prompt length
                lines.append(
                    f"  - [{finding.severity}] {finding.category}: "
                    f"{finding.suggested_fix[:80]}..."
                )

        lines.append("")
        lines.append(f"Current execution ID: {execution_id}")
        lines.append("")
        lines.append(
            "Please analyze these findings and return priorities with improvement direction."
        )

        return "\n".join(lines)

    def _build_json_schema(self) -> dict:
        """
        Build JSON schema for structured LLM output.

        Returns the JSON Schema that matches the PriorityList Pydantic model.

        Returns:
            JSON Schema dict for response_format.
        """
        return {
            "type": "object",
            "properties": {
                "priorities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "finding_index": {
                                "type": "integer",
                                "minimum": 0,
                            },
                            "priority_rank": {
                                "type": "integer",
                                "minimum": 1,
                            },
                            "rationale": {
                                "type": "string",
                                "minLength": 1,
                            },
                        },
                        "required": ["finding_index", "priority_rank", "rationale"],
                        "additionalProperties": False,
                    },
                },
                "improvement_direction": {
                    "type": "string",
                    "minLength": 1,
                },
            },
            "required": ["priorities", "improvement_direction"],
            "additionalProperties": False,
        }
