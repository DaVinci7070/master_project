import logging
import re
from typing import Optional
from collections import Counter

from pydantic import ValidationError

from app.core.llm_client import LLMClient, LLMError
from app.models.schemas.analysis_schemas import AnalysisResult, Finding
from app.models.schemas.telemetry_schemas import ExecutionTelemetryResponse
from app.prompts.analyzer_prompt import ANALYZER_SYSTEM_PROMPT

log = logging.getLogger(__name__)


class AnalyzerService:
    """
    Analyzer agent: generates structured findings from execution telemetry.

    Uses LLM with structured JSON output to produce validated findings.
    Part of the Developer Team's post-execution analysis pipeline.

    Flow:
        Execution completes -> Telemetry captured -> AnalyzerService.analyze_execution()
        -> Findings generated -> Product Owner reviews

    Example:
        llm_client = LLMClient()
        analyzer = AnalyzerService(llm_client=llm_client)

        result = await analyzer.analyze_execution(
            telemetry=execution_telemetry,
            history=recent_executions,
            input_content="user query",
            output_content="agent response"
        )

        for finding in result.findings:
            print(f"{finding.severity}: {finding.category} - {finding.suggested_fix}")
    """

    def __init__(self, llm_client: LLMClient):
        """
        Initialize the Analyzer service.

        Args:
            llm_client: LLMClient for making LLM inference calls.
        """
        self.llm = llm_client

    async def analyze_execution(
        self,
        telemetry: ExecutionTelemetryResponse,
        history: list[ExecutionTelemetryResponse],
        input_content: Optional[str] = None,
        output_content: Optional[str] = None,
    ) -> AnalysisResult:
        """
        Analyze a completed execution and generate findings.

        Sends execution telemetry to the LLM with structured output mode
        to generate actionable findings for improvement.

        Args:
            telemetry: The execution to analyze.
            history: Recent executions for pattern detection (recommended: last 10).
            input_content: Optional full input content (if available).
            output_content: Optional full output content (if available).

        Returns:
            AnalysisResult with list of findings. On any error, returns
            an empty result with error noted in summary.
        """
        log.info(f"Analyzing execution_id={telemetry.execution_id[:8]}...")

        try:
            user_prompt = self._build_analysis_prompt(
                telemetry=telemetry,
                history=history,
                input_content=input_content,
                output_content=output_content,
            )

            result = await self.llm.chat_structured(
                messages=[
                    {"role": "system", "content": ANALYZER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_model=AnalysisResult,
                temperature=0.2,
            )

            result.execution_id = telemetry.execution_id

            log.info(
                f"Analysis complete: {len(result.findings)} findings for "
                f"execution_id={telemetry.execution_id[:8]}..."
            )

            return result

        except LLMError as e:
            log.warning(
                f"LLM error during analysis of execution_id={telemetry.execution_id[:8]}: {e}"
            )
            return AnalysisResult(
                findings=[],
                execution_id=telemetry.execution_id,
                summary=f"Analysis failed due to LLM error: {str(e)[:100]}",
            )

        except ValidationError as e:
            log.warning(
                f"Validation error parsing analysis for execution_id={telemetry.execution_id[:8]}: {e}"
            )
            return AnalysisResult(
                findings=[],
                execution_id=telemetry.execution_id,
                summary=f"Analysis failed due to invalid LLM response format",
            )

        except Exception as e:
            log.error(
                f"Unexpected error analyzing execution_id={telemetry.execution_id[:8]}: {e}",
                exc_info=True,
            )
            return AnalysisResult(
                findings=[],
                execution_id=telemetry.execution_id,
                summary=f"Analysis failed due to unexpected error: {str(e)[:100]}",
            )

    def _build_analysis_prompt(
        self,
        telemetry: ExecutionTelemetryResponse,
        history: list[ExecutionTelemetryResponse],
        input_content: Optional[str] = None,
        output_content: Optional[str] = None,
    ) -> str:
        """
        Build the user prompt with formatted telemetry data.

        Formats the execution telemetry and history into a human-readable
        format for the LLM to analyze.

        Args:
            telemetry: The execution to analyze.
            history: Recent executions for pattern detection.
            input_content: Optional input content.
            output_content: Optional output content.

        Returns:
            Formatted prompt string for the LLM.
        """
        lines = ["## Execution to Analyze", ""]

        lines.append(f"- **Execution ID**: {telemetry.execution_id}")
        lines.append(f"- **Agent ID**: {telemetry.agent_id}")
        lines.append(f"- **Outcome**: {telemetry.outcome}")
        lines.append(f"- **Started**: {telemetry.started_at.isoformat()}")

        if telemetry.completed_at:
            lines.append(f"- **Completed**: {telemetry.completed_at.isoformat()}")

        if telemetry.latency_ms is not None:
            lines.append(f"- **Latency**: {telemetry.latency_ms:.2f}ms")

        if telemetry.tokens_total > 0:
            lines.append(
                f"- **Tokens**: {telemetry.tokens_input} input / "
                f"{telemetry.tokens_output} output / {telemetry.tokens_total} total"
            )

        if telemetry.error_message:
            lines.append(f"- **Error Message**: {telemetry.error_message}")
        if telemetry.error_type:
            lines.append(f"- **Error Type**: {telemetry.error_type}")

        if input_content:
            lines.append("")
            lines.append("### Input Content")
            lines.append("```")
            lines.append(input_content[:2000])
            if len(input_content) > 2000:
                lines.append("... (truncated)")
            lines.append("```")

        if output_content:
            lines.append("")
            lines.append("### Output Content")
            lines.append("```")
            lines.append(output_content[:2000])
            if len(output_content) > 2000:
                lines.append("... (truncated)")
            lines.append("```")

        lines.append("")
        lines.append("## Recent Execution History")
        lines.append("")

        if not history:
            lines.append("No recent history available.")
        else:
            success_count = sum(1 for h in history if h.outcome == "success")
            error_count = sum(1 for h in history if h.outcome == "error")
            timeout_count = sum(1 for h in history if h.outcome == "timeout")
            cancelled_count = sum(1 for h in history if h.outcome == "cancelled")

            latencies = [h.latency_ms for h in history if h.latency_ms is not None]
            avg_latency = sum(latencies) / len(latencies) if latencies else 0

            lines.append(
                f"Recent executions ({len(history)} total): "
                f"{success_count} success, {error_count} errors, "
                f"{timeout_count} timeouts, {cancelled_count} cancelled"
            )
            lines.append(f"Average latency: {avg_latency:.2f}ms")

            error_types = [h.error_type for h in history if h.error_type]
            if error_types:
                lines.append("")
                lines.append("Error types observed:")
                for error_type, count in Counter(error_types).most_common(5):
                    lines.append(f"  - {error_type}: {count} occurrences")

            error_executions = [h for h in history if h.outcome != "success"]
            if error_executions:
                lines.append("")
                lines.append("Non-successful executions:")
                for exec in error_executions[:5]:
                    status = f"[{exec.outcome}]"
                    if exec.error_type:
                        status += f" {exec.error_type}"
                    lines.append(f"  - {exec.execution_id[:8]}... {status}")

        return "\n".join(lines)

    def _build_json_schema(self) -> dict:
        """
        Build JSON schema for structured LLM output.

        Returns the JSON Schema that matches the AnalysisResult Pydantic model.

        Returns:
            JSON Schema dict for response_format.
        """
        return {
            "type": "object",
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "enum": ["prompt", "topology", "skill", "error"],
                            },
                            "severity": {
                                "type": "string",
                                "enum": ["critical", "warning", "info"],
                            },
                            "evidence": {
                                "type": "string",
                                "minLength": 1,
                            },
                            "suggested_fix": {
                                "type": "string",
                                "minLength": 1,
                            },
                        },
                        "required": ["category", "severity", "evidence", "suggested_fix"],
                        "additionalProperties": False,
                    },
                },
                "execution_id": {
                    "type": "string",
                },
                "summary": {
                    "type": "string",
                    "minLength": 1,
                },
            },
            "required": ["findings", "execution_id", "summary"],
            "additionalProperties": False,
        }
