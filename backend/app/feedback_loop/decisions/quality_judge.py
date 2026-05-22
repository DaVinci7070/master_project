"""
Quality Judge Service for LLM-as-judge quality scoring.

This service uses an LLM to evaluate the quality of execution outputs
on a 0-1 scale across multiple dimensions (relevance, accuracy, completeness,
clarity, helpfulness).

Part of the A/B testing infrastructure for measuring quality improvements.
"""
import logging
from pydantic import BaseModel, Field, ValidationError

from app.core.llm_client import LLMClient, LLMError
from app.prompts.quality_judge_prompt import QUALITY_JUDGE_SYSTEM_PROMPT

log = logging.getLogger(__name__)


class QualityScore(BaseModel):
    """
    Quality assessment result from LLM-as-judge.

    Attributes:
        score: Quality score from 0.0 (worst) to 1.0 (best).
        rationale: Explanation for the score, referencing specific criteria.
    """

    score: float = Field(..., ge=0.0, le=1.0, description="Quality score 0.0-1.0")
    rationale: str = Field(
        ..., min_length=10, description="Reasoning for the score (2-3 sentences)"
    )


class QualityJudgeService:
    """
    LLM-as-judge for quality scoring of execution outputs.

    Uses the same LLM as production (via LLMClient) to ensure consistent
    evaluation. Follows AnalyzerService pattern for structured output and
    error handling.

    Flow:
        Execution completes -> ABTestService.record_sample() ->
        QualityJudgeService.score_execution() -> QualityScore returned ->
        Stored in ABTestSample

    Example:
        llm_client = LLMClient()
        judge = QualityJudgeService(llm_client=llm_client)

        score = await judge.score_execution(
            input_content="What is the capital of France?",
            output_content="The capital of France is Paris."
        )

        print(f"Quality: {score.score:.2f} - {score.rationale}")
    """

    def __init__(self, llm_client: LLMClient):
        """
        Initialize the Quality Judge service.

        Args:
            llm_client: LLMClient for making LLM inference calls.
        """
        self.llm = llm_client

    async def score_execution(
        self,
        input_content: str,
        output_content: str,
    ) -> QualityScore:
        """
        Score execution output quality using LLM-as-judge.

        Uses low temperature (0.1) for consistent scoring across evaluations.
        Returns neutral score (0.5) on any error to avoid biasing test results.

        Args:
            input_content: User input/query that the agent was responding to.
            output_content: Agent's response to be evaluated.

        Returns:
            QualityScore with 0-1 score and rationale. Returns neutral score
            (0.5) with error rationale if LLM call fails.
        """
        log.info("Scoring execution output quality via LLM-as-judge...")

        try:
            # Build user prompt with input and output
            user_prompt = self._build_evaluation_prompt(
                input_content=input_content,
                output_content=output_content,
            )

            # Build JSON schema for structured output
            json_schema = self._build_json_schema()

            # Call LLM with structured JSON output
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": QUALITY_JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,  # Low temperature for consistent scoring
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "quality_score",
                        "strict": True,
                        "schema": json_schema,
                    },
                },
            )

            log.debug(f"LLM response: {response.content[:200]}...")

            # Parse and validate the response
            result = QualityScore.model_validate_json(response.content)

            log.info(f"Quality scoring complete: score={result.score:.3f}")

            return result

        except LLMError as e:
            log.warning(f"LLM error during quality scoring: {e}")
            return QualityScore(
                score=0.5,
                rationale=f"Quality scoring failed due to LLM error. Defaulting to neutral score.",
            )

        except ValidationError as e:
            log.warning(f"Validation error parsing quality score: {e}")
            return QualityScore(
                score=0.5,
                rationale=f"Quality scoring failed due to invalid LLM response format. Defaulting to neutral score.",
            )

        except Exception as e:
            log.error(f"Unexpected error during quality scoring: {e}", exc_info=True)
            return QualityScore(
                score=0.5,
                rationale=f"Quality scoring failed due to unexpected error. Defaulting to neutral score.",
            )

    def _build_evaluation_prompt(
        self,
        input_content: str,
        output_content: str,
    ) -> str:
        """
        Build the user prompt with input and output for evaluation.

        Presents the execution context clearly for the LLM to evaluate.

        Args:
            input_content: User input/query.
            output_content: Agent response.

        Returns:
            Formatted prompt string for the LLM.
        """
        # Truncate very long content to prevent token overflow
        max_length = 3000
        input_truncated = input_content[:max_length]
        output_truncated = output_content[:max_length]

        input_suffix = "... (truncated)" if len(input_content) > max_length else ""
        output_suffix = "... (truncated)" if len(output_content) > max_length else ""

        return f"""## User Input

{input_truncated}{input_suffix}

## Agent Response to Evaluate

{output_truncated}{output_suffix}

---

Evaluate this response based on relevance, accuracy, completeness, clarity, and helpfulness. Provide a score from 0.0 to 1.0 and explain your reasoning."""

    def _build_json_schema(self) -> dict:
        """
        Build JSON schema for structured LLM output.

        Returns the JSON Schema that matches the QualityScore Pydantic model.

        Returns:
            JSON Schema dict for response_format.
        """
        return {
            "type": "object",
            "properties": {
                "score": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Quality score from 0.0 to 1.0",
                },
                "rationale": {
                    "type": "string",
                    "minLength": 10,
                    "description": "Explanation for the score (2-3 sentences)",
                },
            },
            "required": ["score", "rationale"],
            "additionalProperties": False,
        }
