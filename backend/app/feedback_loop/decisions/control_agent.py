"""
Control Agent Service for evaluating findings and deciding on improvements.

This service implements the Control Agent from the Developer Team, which
receives prioritized findings from Product Owner, enforces the 3-strike rule,
and uses LLM reasoning to decide which improvements should go to A/B testing.
"""
import hashlib
import logging
from typing import Optional

from pydantic import ValidationError

from app.core.config import settings
from app.core.llm_client import LLMClient, LLMError
from app.models.schemas.analysis_schemas import (
    Finding,
    PriorityList,
    PriorityItem,
    AnalysisFindingResponse,
)
from app.models.schemas.control_schemas import (
    ControlDecision,
    ImprovementAction,
)
from app.repositories.improvement_repository import ImprovementRepository
from app.repositories.finding_repository import FindingRepository
from app.prompts.control_agent_prompt import CONTROL_AGENT_SYSTEM_PROMPT

log = logging.getLogger(__name__)


class ControlAgentService:
    """
    Control Agent: evaluates findings and decides on improvements.

    Uses LLM reasoning to make intelligent decisions about which improvements
    to pursue, while enforcing the 3-strike rule for failed attempts.

    Flow:
        ProductOwnerService.prioritize_findings() -> PriorityList
        -> ControlAgentService.evaluate_findings() -> ControlDecision
        -> A/B testing (Phase 4)

    Example:
        llm_client = LLMClient()
        improvement_repo = ImprovementRepository(session)
        finding_repo = FindingRepository(session)
        control_agent = ControlAgentService(
            llm_client=llm_client,
            improvement_repo=improvement_repo,
            finding_repo=finding_repo
        )

        decision = await control_agent.evaluate_findings(
            priority_list=priority_list,
            findings=findings,
            agent_id="agent-uuid"
        )

        print(f"Approved: {len(decision.approved_improvements)}")
        print(f"Reasoning: {decision.reasoning}")
    """

    def __init__(
        self,
        llm_client: LLMClient,
        improvement_repo: ImprovementRepository,
        finding_repo: FindingRepository,
    ):
        """
        Initialize the Control Agent service.

        Args:
            llm_client: LLMClient for making LLM inference calls.
            improvement_repo: ImprovementRepository for 3-strike rule checks.
            finding_repo: FindingRepository for historical context.
        """
        self.llm = llm_client
        self.improvement_repo = improvement_repo
        self.finding_repo = finding_repo

    async def evaluate_findings(
        self,
        priority_list: PriorityList,
        findings: list[Finding],
        agent_id: str,
    ) -> ControlDecision:
        """
        Evaluate prioritized findings and decide which improvements to pursue.

        Pre-filters findings that have exhausted their 3 strikes, then uses
        LLM reasoning to decide on the remaining findings.

        Args:
            priority_list: Prioritized findings from ProductOwnerService.
            findings: Original findings list (indexed by priority_list).
            agent_id: UUID of the agent being analyzed.

        Returns:
            ControlDecision with approved (max 3), deferred, and rejected findings.
            On any error, returns a valid ControlDecision with empty approved.
        """
        log.info(
            f"Evaluating {len(priority_list.priorities)} prioritized findings "
            f"for agent={agent_id[:8]}..."
        )

        # If no priorities, return empty decision
        if not priority_list.priorities:
            log.info("No priorities to evaluate")
            return ControlDecision(
                approved_improvements=[],
                deferred_findings=[],
                rejected_findings=[],
                reasoning="No prioritized findings to evaluate."
            )

        try:
            # Pre-filter 3-strike findings
            remaining_findings: list[tuple[int, Finding, PriorityItem]] = []
            pre_rejected: list[int] = []
            failed_attempts: dict[str, int] = {}

            for priority in priority_list.priorities:
                finding_idx = priority.finding_index
                if finding_idx >= len(findings):
                    log.warning(
                        f"Finding index {finding_idx} out of range, skipping"
                    )
                    continue

                finding = findings[finding_idx]
                fingerprint = self._generate_fingerprint(finding)

                # Check 3-strike rule
                should_skip = await self.improvement_repo.should_skip_finding(
                    fingerprint, max_attempts=settings.control_agent_max_strikes
                )

                if should_skip:
                    log.info(
                        f"Finding {finding_idx} has exhausted "
                        f"{settings.control_agent_max_strikes} strikes, auto-rejecting"
                    )
                    pre_rejected.append(finding_idx)
                else:
                    remaining_findings.append((finding_idx, finding, priority))
                    # Get attempt count for context
                    attempts = await self.improvement_repo.get_by_fingerprint(
                        fingerprint, limit=settings.control_agent_max_strikes
                    )
                    if attempts:
                        failed_attempts[fingerprint] = len(attempts)

            # If all findings were pre-rejected, return early
            if not remaining_findings:
                log.info("All findings exhausted 3-strike rule, none to evaluate")
                return ControlDecision(
                    approved_improvements=[],
                    deferred_findings=[],
                    rejected_findings=pre_rejected,
                    reasoning="All findings have exhausted their 3-strike limit."
                )

            # Get historical context
            history = await self._get_historical_context(agent_id)

            # Build LLM prompt
            user_prompt = self._build_decision_prompt(
                remaining_findings, history, failed_attempts
            )

            # Build JSON schema for structured output
            json_schema = self._build_json_schema()

            # Call LLM with structured output
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": CONTROL_AGENT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=settings.control_agent_temperature,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "control_decision",
                        "strict": True,
                        "schema": json_schema,
                    },
                },
            )

            log.debug(f"LLM response: {response.content[:200]}...")

            # Parse and validate the response
            llm_decision = ControlDecision.model_validate_json(response.content)

            # Merge pre-rejected findings
            merged_rejected = list(set(llm_decision.rejected_findings + pre_rejected))

            result = ControlDecision(
                approved_improvements=llm_decision.approved_improvements[
                    :settings.control_agent_max_batch
                ],
                deferred_findings=llm_decision.deferred_findings,
                rejected_findings=merged_rejected,
                reasoning=llm_decision.reasoning,
            )

            log.info(
                f"Control decision complete: "
                f"{len(result.approved_improvements)} approved, "
                f"{len(result.deferred_findings)} deferred, "
                f"{len(result.rejected_findings)} rejected"
            )

            return result

        except LLMError as e:
            log.warning(
                f"LLM error during control evaluation for agent={agent_id[:8]}: {e}"
            )
            # Graceful degradation: defer all findings for next cycle
            all_indices = [p.finding_index for p in priority_list.priorities]
            return ControlDecision(
                approved_improvements=[],
                deferred_findings=all_indices,
                rejected_findings=[],
                reasoning=f"LLM evaluation failed, deferring all findings: {str(e)[:100]}"
            )

        except ValidationError as e:
            log.warning(
                f"Validation error parsing control decision for agent={agent_id[:8]}: {e}"
            )
            all_indices = [p.finding_index for p in priority_list.priorities]
            return ControlDecision(
                approved_improvements=[],
                deferred_findings=all_indices,
                rejected_findings=[],
                reasoning="Failed to parse LLM response, deferring all findings."
            )

        except Exception as e:
            log.error(
                f"Unexpected error in control evaluation for agent={agent_id[:8]}: {e}",
                exc_info=True,
            )
            all_indices = [p.finding_index for p in priority_list.priorities]
            return ControlDecision(
                approved_improvements=[],
                deferred_findings=all_indices,
                rejected_findings=[],
                reasoning="Unexpected error during evaluation, deferring all findings."
            )

    def _generate_fingerprint(self, finding: Finding) -> str:
        """
        Generate stable fingerprint for a finding.

        Uses SHA-256 hash of category + normalized suggested_fix to create
        a consistent identifier for the same type of finding across executions.

        Args:
            finding: Finding to generate fingerprint for.

        Returns:
            64-character hex string (SHA-256 hash).
        """
        # Normalize: lowercase and first 200 chars of suggested_fix
        normalized_fix = finding.suggested_fix[:200].lower().strip()
        content = f"{finding.category}:{normalized_fix}"

        return hashlib.sha256(content.encode()).hexdigest()

    async def _get_historical_context(
        self,
        agent_id: str,
    ) -> list[AnalysisFindingResponse]:
        """
        Get historical findings for context.

        Queries recent findings for the agent to provide trend awareness
        to the LLM for better decision making.

        Args:
            agent_id: UUID of the agent.

        Returns:
            List of recent findings for context.
        """
        limit = settings.control_agent_history_days * 3  # ~3 findings per day
        log.debug(
            f"Getting historical context for agent={agent_id[:8]}..., limit={limit}"
        )

        try:
            findings = await self.finding_repo.get_by_agent_id(agent_id, limit=limit)
            return [
                AnalysisFindingResponse.model_validate(f) for f in findings
            ]
        except Exception as e:
            log.warning(f"Error getting historical context: {e}")
            return []

    def _build_decision_prompt(
        self,
        findings: list[tuple[int, Finding, PriorityItem]],
        history: list[AnalysisFindingResponse],
        failed_attempts: dict[str, int],
    ) -> str:
        """
        Build user prompt with findings, history, and failed attempt context.

        Args:
            findings: Tuples of (index, finding, priority) for remaining findings.
            history: Historical findings for trend awareness.
            failed_attempts: Dict mapping fingerprint to attempt count.

        Returns:
            Formatted prompt string for the LLM.
        """
        lines = ["## Prioritized Findings to Evaluate", ""]

        # List each finding with its priority and any failed attempt history
        for idx, finding, priority in findings:
            fingerprint = self._generate_fingerprint(finding)
            attempt_count = failed_attempts.get(fingerprint, 0)

            lines.append(f"### Finding {idx} (Priority Rank: {priority.priority_rank})")
            lines.append(f"- **Category**: {finding.category}")
            lines.append(f"- **Severity**: {finding.severity}")
            lines.append(f"- **Evidence**: {finding.evidence}")
            lines.append(f"- **Suggested Fix**: {finding.suggested_fix}")
            lines.append(f"- **Priority Rationale**: {priority.rationale}")
            if attempt_count > 0:
                remaining = settings.control_agent_max_strikes - attempt_count
                lines.append(
                    f"- **Prior Attempts**: {attempt_count} failed "
                    f"({remaining} remaining before 3-strike rejection)"
                )
            lines.append("")

        # Add historical context
        lines.append("## Historical Context (Recent Agent Findings)")
        lines.append("")

        if not history:
            lines.append("No historical findings available.")
        else:
            # Summary statistics
            severity_counts: dict[str, int] = {}
            category_counts: dict[str, int] = {}
            for h in history:
                severity_counts[h.severity] = severity_counts.get(h.severity, 0) + 1
                category_counts[h.category] = category_counts.get(h.category, 0) + 1

            lines.append(
                f"Last {len(history)} findings: "
                f"{severity_counts.get('critical', 0)} critical, "
                f"{severity_counts.get('warning', 0)} warning, "
                f"{severity_counts.get('info', 0)} info"
            )
            lines.append("")

            # Pattern detection
            repeated = [cat for cat, count in category_counts.items() if count >= 3]
            if repeated:
                lines.append("**Recurring patterns (3+ occurrences):**")
                for cat in repeated:
                    lines.append(f"  - {cat}: {category_counts[cat]} times")
                lines.append("")

            # Recent findings brief
            lines.append("Recent findings (most recent first):")
            for h in history[:5]:
                lines.append(
                    f"  - [{h.severity}] {h.category}: "
                    f"{h.suggested_fix[:60]}..."
                )

        lines.append("")
        lines.append(
            f"Batch size limit: {settings.control_agent_max_batch} improvements max."
        )
        lines.append("")
        lines.append(
            "Analyze these findings and return a ControlDecision with "
            "approved_improvements, deferred_findings, rejected_findings, and reasoning."
        )

        return "\n".join(lines)

    def _build_json_schema(self) -> dict:
        """
        Build JSON schema for structured LLM output.

        Returns the JSON Schema matching the ControlDecision Pydantic model.

        Returns:
            JSON Schema dict for response_format.
        """
        return {
            "type": "object",
            "properties": {
                "approved_improvements": {
                    "type": "array",
                    "maxItems": settings.control_agent_max_batch,
                    "items": {
                        "type": "object",
                        "properties": {
                            "finding_index": {
                                "type": "integer",
                                "minimum": 0,
                            },
                            "artifact_type": {
                                "type": "string",
                                "enum": ["prompt", "agent", "skill"],
                            },
                            "artifact_id": {
                                "type": "string",
                                "minLength": 36,
                                "maxLength": 36,
                            },
                            "improvement_description": {
                                "type": "string",
                                "minLength": 10,
                            },
                            "metric_weights": {
                                "type": "object",
                                "properties": {
                                    "quality": {
                                        "type": "number",
                                        "minimum": 0,
                                        "maximum": 1,
                                    },
                                    "latency": {
                                        "type": "number",
                                        "minimum": 0,
                                        "maximum": 1,
                                    },
                                    "error_rate": {
                                        "type": "number",
                                        "minimum": 0,
                                        "maximum": 1,
                                    },
                                },
                                "required": ["quality", "latency", "error_rate"],
                                "additionalProperties": False,
                            },
                            "rationale": {
                                "type": "string",
                                "minLength": 10,
                            },
                        },
                        "required": [
                            "finding_index",
                            "artifact_type",
                            "artifact_id",
                            "improvement_description",
                            "metric_weights",
                            "rationale",
                        ],
                        "additionalProperties": False,
                    },
                },
                "deferred_findings": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0},
                },
                "rejected_findings": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0},
                },
                "reasoning": {
                    "type": "string",
                    "minLength": 20,
                },
            },
            "required": [
                "approved_improvements",
                "deferred_findings",
                "rejected_findings",
                "reasoning",
            ],
            "additionalProperties": False,
        }
