import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.models.api.report_models import (
    PreProcessTranscriptRequest, QuestionsToTranscriptResponse,
    AskTranscriptQuestionRequest, AskTranscriptQuestionResponse
)
from app.services.assistant_service import AssistantService
from app.dependencies.dependencies import get_assistant_service
from app.dependencies.auth import get_current_user_id

router = APIRouter(prefix="/assistant", tags=["assistant"])

log = logging.getLogger(__name__)

@router.post("/check-questions", response_model=QuestionsToTranscriptResponse)
async def check_questions(
        request: PreProcessTranscriptRequest,
        user_id: str = Depends(get_current_user_id),
        service: AssistantService = Depends(get_assistant_service),
) -> QuestionsToTranscriptResponse:
    try:
        return await service.check_questions(user_id, request)
    except Exception as e:
        log.error(f"[ERROR] {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/ask", response_model=AskTranscriptQuestionResponse)
async def ask_assistant(
        request: AskTranscriptQuestionRequest,
        user_id: str = Depends(get_current_user_id),
        service: AssistantService = Depends(get_assistant_service),
) -> AskTranscriptQuestionResponse:
    try:
        return await service.ask_assistant(user_id, request)
    except Exception as e:
        log.error(f"[ERROR] {e}")
        raise HTTPException(status_code=500, detail=str(e))
