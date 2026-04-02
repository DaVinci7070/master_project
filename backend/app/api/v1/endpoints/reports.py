from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api.report_models import ReportResponse
from app.models.api.report_models import BatchUploadRequest, BatchUploadResponse
from app.services.report_service import ReportService
from app.dependencies.dependencies import get_report_service, get_db_session
from app.dependencies.auth import get_current_user_id

router = APIRouter(prefix="/reports", tags=["reports"])

@router.post("/{report_id}/finalize", response_model=ReportResponse)
async def finalize_report(
    report_id: str,
    user_id: str = Depends(get_current_user_id),
    service: ReportService = Depends(get_report_service),
) -> ReportResponse:
    try:
        return await service.finalize_report(report_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.post("/batch", response_model=BatchUploadResponse)
async def upload_reports_batch(
    data: BatchUploadRequest,
    user_id: str = Depends(get_current_user_id),
    service: ReportService = Depends(get_report_service),
) -> BatchUploadResponse:
    return await service.store_reports_batch(data)

from app.models.api.report_models import ReportResponse, PaginatedReportResponse

@router.get("/user", response_model=PaginatedReportResponse)
async def get_reports_for_user(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    user_id: str = Depends(get_current_user_id),
    service: ReportService = Depends(get_report_service),
) -> PaginatedReportResponse:
    return await service.get_user_reports(user_id, skip, limit)

@router.delete("/{report_id}", response_model=dict)
async def delete_report(
    report_id: str,
    user_id: str = Depends(get_current_user_id),
    service: ReportService = Depends(get_report_service),
) -> dict:
    try:
         return await service.delete_report(user_id, report_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
