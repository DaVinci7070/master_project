import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.models.api.report_models import GenerateReportRequest, GenerateReportResponse
from app.services.report_service import ReportService
from app.dependencies.dependencies import get_report_service
from app.dependencies.auth import get_current_user_id

router = APIRouter(prefix="/transcripts", tags=["transcripts"])

log = logging.getLogger(__name__)

@router.post("/generate", response_model=GenerateReportResponse)
async def generate_report(
        request: GenerateReportRequest,
        user_id: str = Depends(get_current_user_id),
        service: ReportService = Depends(get_report_service),
) -> GenerateReportResponse:

    try:
        return await service.generate_report_from_transcript(user_id, request)
    except Exception as e:
        log.error(f"[ERROR] {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/intake", response_model=GenerateReportResponse)
async def generate_report_intake(
        request: GenerateReportRequest,
        user_id: str = Depends(get_current_user_id),
        service: ReportService = Depends(get_report_service),
) -> GenerateReportResponse:
    pass
