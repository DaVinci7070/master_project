import logging
from fastapi import APIRouter, Depends, HTTPException
from app.models.api.report_models import SubmitAnswersRequest, GenerateReportResponse
from app.services.report_service import ReportService
from app.dependencies.dependencies import get_report_service
from app.dependencies.auth import get_current_user_id

router = APIRouter(prefix="/orchestration", tags=["orchestration"])
log = logging.getLogger(__name__)

@router.post("/resume", response_model=GenerateReportResponse)
async def resume_orchestration(
    request: SubmitAnswersRequest,
    user_id: str = Depends(get_current_user_id),
    service: ReportService = Depends(get_report_service)
) -> GenerateReportResponse:
    try:
        return await service.resume_orchestration_with_answers(user_id=user_id, request=request)
    except Exception as e:
        log.error(f"[ORCHESTRATION] Error resuming run {request.run_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
