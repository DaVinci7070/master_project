"""Gap detector for identifying capability deficiencies."""
import logging
import os
from typing import Callable, Awaitable, Optional

from app.models.schemas.analysis_schemas import (
    ConfidenceLevel, GapType, GapSeverity, CapabilityGap, CapabilityAssessment
)
from app.orchestration.analysis.models import (
    AssessmentContext, CapabilityType, GapDetectionResponse,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.orchestration.analysis.feasibility_judge import FeasibilityJudge

logger = logging.getLogger(__name__)

# Thresholds for capability matching (configurable via ENV)
# Lowered from 0.95 to 0.90 - 0.95 was too strict and caused false negatives
CAN_DO_THRESHOLD = float(os.getenv("CAPABILITY_CAN_DO_THRESHOLD", "0.90"))
MAYBE_THRESHOLD = float(os.getenv("CAPABILITY_MAYBE_THRESHOLD", "0.50"))

# LLM prompt for nuanced gap identification
GAP_IDENTIFICATION_PROMPT = """You are analyzing a system's capability to handle a challenge.

## Challenge
{challenge_text}

## Required Capabilities
{required_capabilities}

## Capability Match Scores
{match_scores}

## Topology Issues
{topology_issues}

## Similar Past Successes
{similar_successes}

Identify specific gaps between what's required and what's available.
For each gap, specify:
- gap_type: one of [missing_skill, missing_planning_skill, weak_prompt, topology_issue, missing_agent, schema_mismatch]
  - missing_skill: agent needs executable code/tool (API calls, data processing, file handling, computation)
  - missing_planning_skill: agent needs reasoning instructions (validation rules, decision logic, format guidelines, domain knowledge)
  - weak_prompt: agent exists but prompt is too weak for this capability
  - topology_issue: dependency or routing problem
  - missing_agent: no suitable agent exists
  - schema_mismatch: input/output schema incompatibility
- severity: one of [critical, important, minor]
  - critical: blocks execution entirely
  - important: significantly degrades quality
  - minor: workaround exists
- description: brief explanation (max 100 chars)
- affected_capability: which capability is affected

Only list actual gaps based on low match scores (<0.7) or topology issues.
If all capabilities match well (>0.95), return empty gaps list."""


class GapDetector:
    """
    Identifies capability gaps and computes confidence verdict.

    Takes AssessmentContext from ChallengeAnalyzer and produces:
    - List of CapabilityGap with type, severity, description
    - ConfidenceLevel (CAN_DO, MAYBE, CANNOT_DO)
    - Improvement suggestions when confidence is low
    """

    def __init__(
        self,
        feasibility_judge: Optional["FeasibilityJudge"] = None,
        structured_llm_fn: Optional[Callable] = None,
    ):
        """
        Initialize gap detector.

        Args:
            feasibility_judge: Optional judge that verifies execution capabilities
            structured_llm_fn: Async function(messages, response_model, **kwargs) -> BaseModel
        """
        self._structured_llm_fn = structured_llm_fn
        self._feasibility_judge = feasibility_judge

    async def detect_gaps(
        self,
        context: AssessmentContext
    ) -> tuple[list[CapabilityGap], ConfidenceLevel, list[str]]:
        """
        Detect capability gaps and compute confidence level.

        Args:
            context: Assessment context from ChallengeAnalyzer

        Returns:
            (gaps, confidence_level, factors)
        """
        # 1. Check for immediate CANNOT_DO conditions
        cannot_do_gaps, cannot_do_factors = self._check_cannot_do_conditions(context)
        if cannot_do_gaps:
            # Limit factors to avoid validation errors
            return cannot_do_gaps, ConfidenceLevel.CANNOT_DO, cannot_do_factors[:5]

        # 2. Check for CAN_DO conditions (all capabilities sufficient)
        if await self._all_capabilities_sufficient(context):
            factors = ["All required capabilities matched"]
            if context.confidence_boost > 0:
                factors.append("Similar past successes found")
            return [], ConfidenceLevel.CAN_DO, factors

        # 3. MAYBE case - use LLM for nuanced gap identification
        gaps = await self._identify_gaps_with_llm(context)

        # Add gaps from feasibility check (execution capabilities without tool backing)
        for infeasible in context.infeasible_capabilities:
            gap = CapabilityGap(
                gap_type=GapType.MISSING_SKILL,
                severity=GapSeverity.CRITICAL,
                description=f"No executable skill/tool: {infeasible.reason[:80]}",
                affected_capability=infeasible.required_capability,
            )
            gaps.append(gap)

        factors = self._build_maybe_factors(context, gaps)

        return gaps, ConfidenceLevel.MAYBE, factors

    def _check_cannot_do_conditions(
        self,
        context: AssessmentContext
    ) -> tuple[list[CapabilityGap], list[str]]:
        """
        Check for conditions that immediately result in CANNOT_DO.

        Per RESEARCH:
        - Any capability < MAYBE_THRESHOLD (0.5)
        - Critical dependency issues
        - Critical schema issues
        """
        gaps = []
        factors = []

        # Check for very low capability matches
        for match in context.capability_matches:
            if match.similarity_score < MAYBE_THRESHOLD:
                gap = CapabilityGap(
                    gap_type=GapType.MISSING_SKILL,
                    severity=GapSeverity.CRITICAL,
                    description=f"No adequate match found (score: {match.similarity_score:.2f})",
                    affected_capability=match.required_capability
                )
                gaps.append(gap)
                factors.append(f"Missing: {match.required_capability}")

        # Check topology dependency issues
        if context.topology_capabilities and context.topology_capabilities.has_dependency_issues:
            for issue in context.topology_capabilities.dependency_issues[:2]:
                gap = CapabilityGap(
                    gap_type=GapType.TOPOLOGY_ISSUE,
                    severity=GapSeverity.CRITICAL,
                    description=issue[:100],
                    affected_capability="topology_validation"
                )
                gaps.append(gap)
            factors.append("Topology dependency issues detected")

        # Check schema issues
        for issue in context.schema_issues[:2]:
            gap = CapabilityGap(
                gap_type=GapType.SCHEMA_MISMATCH,
                severity=GapSeverity.CRITICAL,
                description=issue[:100],
                affected_capability="schema_validation"
            )
            gaps.append(gap)
            factors.append("Schema compatibility issues")

        return gaps, factors

    async def _all_capabilities_sufficient(self, context: AssessmentContext) -> bool:
        """Check if all capabilities meet CAN_DO threshold and pass feasibility check."""
        if not context.capability_matches:
            return False

        for match in context.capability_matches:
            # Apply confidence boost from similar successes (capped at 30% relative increase
            # to prevent weak matches from being promoted to CAN_DO)
            boosted_score = min(
                match.similarity_score + context.confidence_boost,
                match.similarity_score * 1.3,
            )
            if boosted_score < CAN_DO_THRESHOLD:
                return False

        # Also check for any topology/schema issues
        if context.topology_capabilities and context.topology_capabilities.has_dependency_issues:
            return False
        if context.schema_issues:
            return False

        # NEW: Feasibility check for execution-type capabilities
        # Even if embedding scores are high, verify that the matched agents
        # actually have tools/skills to perform execution tasks
        if self._feasibility_judge:
            execution_matches = [
                m for m in context.capability_matches
                if m.capability_type == CapabilityType.EXECUTION
            ]
            if execution_matches:
                results = await self._feasibility_judge.verify_execution_capabilities(
                    context, execution_matches
                )
                infeasible = [r for r in results if not r.feasible]
                if infeasible:
                    # Store results on context for gap creation downstream
                    context.infeasible_capabilities = infeasible
                    logger.info(
                        f"Feasibility check failed for {len(infeasible)} execution capabilities: "
                        f"{[r.required_capability for r in infeasible]}"
                    )
                    return False

        return True

    async def _identify_gaps_with_llm(
        self,
        context: AssessmentContext
    ) -> list[CapabilityGap]:
        """
        Use LLM for nuanced gap identification in MAYBE cases.

        LLM helps identify:
        - Which gaps are most impactful
        - Whether "close but not quite" matches might work
        - Subtle topology or schema issues
        """
        if not self._structured_llm_fn:
            logger.warning("No LLM function, using rule-based gap identification")
            return self._rule_based_gap_identification(context)

        # Build match scores string
        match_scores = "\n".join(
            f"- {m.required_capability}: {m.similarity_score:.2f} "
            f"(matched: {m.matched_capability or 'none'})"
            for m in context.capability_matches
        )

        # Build topology issues string
        topology_issues = "None"
        if context.topology_capabilities and context.topology_capabilities.dependency_issues:
            topology_issues = "\n".join(
                f"- {issue}" for issue in context.topology_capabilities.dependency_issues
            )
        if context.schema_issues:
            topology_issues += "\n" + "\n".join(f"- {issue}" for issue in context.schema_issues)

        # Build similar successes string
        similar_successes = "None found"
        if context.similar_successes:
            similar_successes = "\n".join(
                f"- {s.get('text', 'Unknown')[:100]} (confidence: {s.get('confidence', 0):.2f})"
                for s in context.similar_successes[:5]
            )

        prompt = GAP_IDENTIFICATION_PROMPT.format(
            challenge_text=context.challenge_text[:1000],
            required_capabilities=", ".join(context.required_capabilities),
            match_scores=match_scores,
            topology_issues=topology_issues,
            similar_successes=similar_successes
        )

        messages = [
            {"role": "system", "content": "You identify capability gaps precisely."},
            {"role": "user", "content": prompt}
        ]

        try:
            result = await self._structured_llm_fn(
                messages, GapDetectionResponse, temperature=0.2,
            )
            gaps = result.gaps

            # Sort by severity: critical first, then important, then minor
            severity_order = {GapSeverity.CRITICAL: 0, GapSeverity.IMPORTANT: 1, GapSeverity.MINOR: 2}
            gaps.sort(key=lambda g: severity_order[g.severity])

            return gaps

        except Exception as e:
            logger.error(f"LLM gap identification failed: {e}")
            return self._rule_based_gap_identification(context)

    def _rule_based_gap_identification(
        self,
        context: AssessmentContext
    ) -> list[CapabilityGap]:
        """Fallback rule-based gap identification when LLM unavailable."""
        gaps = []

        for match in context.capability_matches:
            if match.similarity_score < CAN_DO_THRESHOLD:
                # Determine severity based on score
                if match.similarity_score < MAYBE_THRESHOLD:
                    severity = GapSeverity.CRITICAL
                elif match.similarity_score < 0.7:
                    severity = GapSeverity.IMPORTANT
                else:
                    severity = GapSeverity.MINOR

                # Determine gap type based on capability type
                if match.matched_capability is None:
                    # No match at all — classify by capability type
                    if match.capability_type == CapabilityType.KNOWLEDGE:
                        gap_type = GapType.MISSING_PLANNING_SKILL
                    else:
                        gap_type = GapType.MISSING_SKILL
                elif match.capability_type == CapabilityType.KNOWLEDGE:
                    gap_type = GapType.MISSING_PLANNING_SKILL  # Weak knowledge match
                else:
                    gap_type = GapType.WEAK_PROMPT  # Partial execution match

                gap = CapabilityGap(
                    gap_type=gap_type,
                    severity=severity,
                    description=f"Match score {match.similarity_score:.2f} below threshold",
                    affected_capability=match.required_capability
                )
                gaps.append(gap)

        # Sort by severity
        severity_order = {GapSeverity.CRITICAL: 0, GapSeverity.IMPORTANT: 1, GapSeverity.MINOR: 2}
        gaps.sort(key=lambda g: severity_order[g.severity])

        return gaps

    def _build_maybe_factors(
        self,
        context: AssessmentContext,
        gaps: list[CapabilityGap]
    ) -> list[str]:
        """Build top factors list for MAYBE verdict."""
        factors = []

        # Count gap types
        critical_count = sum(1 for g in gaps if g.severity == GapSeverity.CRITICAL)
        important_count = sum(1 for g in gaps if g.severity == GapSeverity.IMPORTANT)

        if critical_count > 0:
            factors.append(f"{critical_count} critical gap(s)")
        if important_count > 0:
            factors.append(f"{important_count} important gap(s)")

        # Add partial match info
        partial_matches = [
            m for m in context.capability_matches
            if MAYBE_THRESHOLD <= m.similarity_score < CAN_DO_THRESHOLD
        ]
        if partial_matches:
            caps = [m.required_capability for m in partial_matches[:2]]
            factors.append(f"Partial match: {', '.join(caps)}")

        return factors[:2]  # Max 2 factors per CONTEXT

    def generate_suggestions(
        self,
        gaps: list[CapabilityGap]
    ) -> list[str]:
        """
        Generate improvement suggestions based on identified gaps.

        Per CONTEXT: Include improvement suggestions when confidence is low.
        """
        suggestions = []

        for gap in gaps:
            if gap.severity in (GapSeverity.CRITICAL, GapSeverity.IMPORTANT):
                if gap.gap_type == GapType.MISSING_SKILL:
                    suggestions.append(f"Add functional skill (executable code) for: {gap.affected_capability}")
                elif gap.gap_type == GapType.MISSING_PLANNING_SKILL:
                    suggestions.append(f"Add planning skill (reasoning guidelines) for: {gap.affected_capability}")
                elif gap.gap_type == GapType.WEAK_PROMPT:
                    suggestions.append(f"Improve prompt for: {gap.affected_capability}")
                elif gap.gap_type == GapType.MISSING_AGENT:
                    suggestions.append(f"Add agent with capability: {gap.affected_capability}")
                elif gap.gap_type == GapType.TOPOLOGY_ISSUE:
                    suggestions.append(f"Fix topology: {gap.description}")
                elif gap.gap_type == GapType.SCHEMA_MISMATCH:
                    suggestions.append(f"Update schema for: {gap.affected_capability}")

        return suggestions[:5]  # Limit suggestions

    async def build_assessment(
        self,
        context: AssessmentContext
    ) -> CapabilityAssessment:
        """
        Build complete capability assessment from context.

        This is the main entry point that produces the final assessment.
        """
        gaps, confidence, factors = await self.detect_gaps(context)

        # Generate suggestions for non-CAN_DO cases
        suggestions = []
        if confidence != ConfidenceLevel.CAN_DO:
            suggestions = self.generate_suggestions(gaps)

        assessment = CapabilityAssessment(
            confidence=confidence,
            reasoning=f"Analyzed {len(context.required_capabilities)} required capabilities.",
            top_factors=factors,
            gaps=gaps,
            improvement_suggestions=suggestions,
            similar_past_success=len(context.similar_successes) > 0
        )

        logger.info(
            f"Assessment complete: {confidence.value} "
            f"({len(gaps)} gaps, {len(suggestions)} suggestions)"
        )

        return assessment
