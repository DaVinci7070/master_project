import hashlib
import logging
from typing import Optional
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schemas.analysis_schemas import (
    Finding,
    PriorityList,
)
from app.models.schemas.control_schemas import ControlDecision
from app.models.schemas.evolution_schemas import EvolutionReport
from app.models.sql.agent_event_models import AgentExecutionEvent
from app.repositories.improvement_repository import ImprovementRepository
from app.feedback_loop.analysis.pipeline import AnalysisPipeline
from app.feedback_loop.decisions.control_agent import ControlAgentService
from app.feedback_loop.improvement.orchestrator import ImprovementOrchestrator

log = logging.getLogger(__name__)

_ORCHESTRATOR_AGENT_ID = "orchestrator"


class EvolutionLoopService:
    """Chains analysis -> decision -> improvement after an execution."""

    def __init__(
        self,
        db: AsyncSession,
        analysis_pipeline: AnalysisPipeline,
        control_agent: ControlAgentService,
        improvement_orchestrator: ImprovementOrchestrator,
        improvement_repo: ImprovementRepository,
    ):
        self.db = db
        self.analysis_pipeline = analysis_pipeline
        self.control_agent = control_agent
        self.improvement_orchestrator = improvement_orchestrator
        self.improvement_repo = improvement_repo

    async def run_post_execution_evolution(
        self,
        execution_id: str,
        output_content: Optional[str] = None,
    ) -> EvolutionReport:
        """
        Main entry point: analyze -> prioritize -> decide -> improve.

        Returns a structured report with attempt counts. Always emits
        evolution.triggered + evolution.completed (or evolution.failed).
        """
        await self._emit_event(
            execution_id=execution_id,
            event_type="evolution.triggered",
            data={"execution_id": execution_id},
        )

        try:
            findings_response, priority_list = (
                await self.analysis_pipeline.run(
                    execution_id,
                    output_content=output_content,
                )
            )

            if not findings_response:
                report = EvolutionReport(
                    execution_id=execution_id,
                    attempted=0,
                    succeeded=0,
                    reason="no_findings",
                )
                await self._emit_event(
                    execution_id=execution_id,
                    event_type="evolution.completed",
                    data=report.model_dump(),
                )
                return report

            agent_id = await self._resolve_agent_id(
                execution_id=execution_id,
                findings_response=findings_response,
            )
            if agent_id is None:
                report = EvolutionReport(
                    execution_id=execution_id,
                    attempted=0,
                    succeeded=0,
                    reason="no_agent_id",
                )
                await self._emit_event(
                    execution_id=execution_id,
                    event_type="evolution.completed",
                    data=report.model_dump(),
                )
                return report

            findings: list[Finding] = [
                Finding(
                    category=f.category,
                    severity=f.severity,
                    evidence=f.evidence,
                    suggested_fix=f.suggested_fix,
                )
                for f in findings_response
            ]

            decision: ControlDecision = await self.control_agent.evaluate_findings(
                priority_list=priority_list,
                findings=findings,
                agent_id=agent_id,
            )

            skipped_by_strike = 0
            for rejected_idx in decision.rejected_findings:
                if rejected_idx < 0 or rejected_idx >= len(findings):
                    continue
                finding = findings[rejected_idx]
                fingerprint = self._fingerprint(finding)
                if await self.improvement_repo.should_skip_finding(fingerprint):
                    skipped_by_strike += 1
                    await self._emit_event(
                        execution_id=execution_id,
                        event_type="evolution.skipped_by_strike",
                        agent_id=agent_id,
                        data={
                            "execution_id": execution_id,
                            "finding_fingerprint": fingerprint,
                        },
                    )

            attempted = 0
            succeeded = 0
            for action in decision.approved_improvements:
                if action.finding_index >= len(findings):
                    log.warning(
                        "ImprovementAction finding_index %s out of range (len=%s)",
                        action.finding_index,
                        len(findings),
                    )
                    continue

                attempted += 1
                await self._emit_event(
                    execution_id=execution_id,
                    event_type="evolution.finding_detected",
                    agent_id=agent_id,
                    data={
                        "execution_id": execution_id,
                        "artifact_type": action.artifact_type,
                        "artifact_id": action.artifact_id,
                        "finding_index": action.finding_index,
                    },
                )

                ab_test_id = await self.improvement_orchestrator.execute_improvement(
                    action=action,
                    finding=findings[action.finding_index],
                    agent_id=agent_id,
                )

                if ab_test_id:
                    succeeded += 1
                    event_type = (
                        "evolution.prompt_updated"
                        if action.artifact_type == "prompt"
                        else "evolution.skill_rebuilt"
                        if action.artifact_type == "skill"
                        else "evolution.agent_updated"
                    )
                    await self._emit_event(
                        execution_id=execution_id,
                        event_type=event_type,
                        agent_id=agent_id,
                        data={
                            "execution_id": execution_id,
                            "artifact_type": action.artifact_type,
                            "artifact_id": action.artifact_id,
                            "ab_test_id": ab_test_id,
                            "rationale": action.rationale,
                        },
                    )

            report = EvolutionReport(
                execution_id=execution_id,
                attempted=attempted,
                succeeded=succeeded,
                skipped_by_strike=skipped_by_strike,
            )
            await self._emit_event(
                execution_id=execution_id,
                event_type="evolution.completed",
                data=report.model_dump(),
            )
            return report

        except Exception as exc:
            log.exception(
                "Evolution loop failed for execution_id=%s", execution_id
            )
            await self._emit_event(
                execution_id=execution_id,
                event_type="evolution.failed",
                data={"execution_id": execution_id, "error": str(exc)[:500]},
            )
            raise


    async def _resolve_agent_id(
        self,
        execution_id: str,
        findings_response,
    ) -> Optional[str]:
        """
        Resolve the agent_id for this execution.

        AnalysisFindingResponse has execution_telemetry_id but not agent_id.
        We look up the telemetry row to get the agent_id.
        """
        try:
            telemetry = await (
                self.analysis_pipeline.telemetry.get_by_execution_id(execution_id)
            )
        except Exception as e:
            log.warning("Could not resolve agent_id for %s: %s", execution_id, e)
            return None
        if telemetry is None:
            return None
        return telemetry.agent_id

    def _fingerprint(self, finding: Finding) -> str:
        """Matches ControlAgentService._generate_fingerprint (bit-for-bit)."""
        normalized_fix = finding.suggested_fix[:200].lower().strip()
        content = f"{finding.category}:{normalized_fix}"
        return hashlib.sha256(content.encode()).hexdigest()

    async def _emit_event(
        self,
        execution_id: str,
        event_type: str,
        data: Optional[dict] = None,
        agent_id: Optional[str] = None,
    ) -> None:
        """
        Persist an evolution.* event as an AgentExecutionEvent row.

        Uses the same DB session the service was constructed with (already
        isolated from the main execution session by the caller).
        """
        try:
            event = AgentExecutionEvent(
                id=str(uuid4()),
                execution_id=execution_id,
                agent_id=agent_id or _ORCHESTRATOR_AGENT_ID,
                agent_name="evolution_loop",
                event_type=event_type,
                wave=None,
                data=data or {},
            )
            self.db.add(event)
            await self.db.commit()
        except Exception as e:
            log.warning(
                "Failed to emit evolution event %s for %s: %s",
                event_type,
                execution_id,
                e,
            )
            try:
                await self.db.rollback()
            except Exception:
                pass