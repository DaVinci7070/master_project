import logging
import httpx
import json
from typing import Any, List, Optional

from app.models.api.report_models import (
    PreProcessTranscriptRequest, QuestionsToTranscriptResponse,
    AskTranscriptQuestionRequest, AskTranscriptQuestionResponse
)
from app.repositories.qdrant_repository import QdrantReportsRepository
from app.adapters.sql_protocols import ReportRepositoryProtocol
from app.core.config import settings

log = logging.getLogger("assistant-service")

class AssistantService:

    def __init__(
        self,
        qdrant_repo: QdrantReportsRepository,
        postgres_repo: ReportRepositoryProtocol,
    ):
        self.qdrant_repo = qdrant_repo
        self.postgres_repo = postgres_repo

    async def check_questions(self, user_id: str, request: PreProcessTranscriptRequest) -> QuestionsToTranscriptResponse:
        payload: dict[str, Any] = {
            "user_id": user_id,
            "transcript": request.transcript,
            "n_questions": getattr(request, "n_questions", 8),
            "language": getattr(request, "language", "de"),
            "template": None,
        }

        if request.template_id:
            template_hit = self.qdrant_repo.get_template_by_id(
                user_id,
                request.template_id,
                include_text=True,
            )

            if template_hit:
                payload["template"] = {
                    "template_id": str(template_hit.template_id),
                    "name": template_hit.name,
                    "content": template_hit.content or {},
                }
            else:
                payload["template"] = None

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{settings.gpu_url}/question_agent/preprocess", json=payload)
            resp.raise_for_status()
            data = resp.json()

        questions_out = data.get("questions", []) or []
        questions: List[str] = [
            str(q["question"]).strip()
            for q in questions_out
            if isinstance(q, dict) and q.get("question")
        ]

        return QuestionsToTranscriptResponse(questions=questions)

    async def ask_assistant(self, user_id: str, request: AskTranscriptQuestionRequest) -> AskTranscriptQuestionResponse:
        report_content = None
        report = None
        r_id = None
        if request.report_id:
            try:
                r_id = str(request.report_id) 
                report = await self.postgres_repo.get_report_by_id(r_id)
                if report:
                    report_content = (
                        json.dumps(report.report_content, ensure_ascii=False)
                        if isinstance(report.report_content, (dict, list))
                        else str(report.report_content)
                    )
            except (ValueError, TypeError):
                 log.warning(f"Invalid report_id={request.report_id} provided for question processing")
        payload: dict[str, Any] = {
            "user_id": user_id,
            "transcript": request.transcript,
            "question": request.question,
            "report_content": report_content,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{settings.gpu_url}/question_agent/answer", json=payload)
            resp.raise_for_status()
            data = resp.json()

        return AskTranscriptQuestionResponse(
            user_id=user_id,
            answer=data.get("answer", ""),
            report_id=str(r_id) if (request.report_id and report) else None
        )
