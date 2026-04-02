from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api.template_models import TemplateUploadRequest, TemplateUploadResponse, TemplateDetail, TemplateResponse
from app.dependencies.dependencies import get_db_session
from app.services.template_service import TemplateService
from app.dependencies.dependencies import get_template_service
from app.dependencies.auth import get_current_user_id

router = APIRouter(prefix="/templates", tags=["templates"])

@router.post("", response_model=TemplateUploadResponse)
async def upload_template(
    data: TemplateUploadRequest,
    user_id: str = Depends(get_current_user_id),
    service: TemplateService = Depends(get_template_service),
) -> TemplateUploadResponse:

    return await service.store_template(user_id, data)

@router.get("/user", response_model=list[TemplateDetail])
async def list_templates(
    user_id: str = Depends(get_current_user_id),
    service: TemplateService = Depends(get_template_service),
) -> list[TemplateDetail]:
    return await service.get_user_templates(user_id)


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: str,
    user_id: str = Depends(get_current_user_id),
    service: TemplateService = Depends(get_template_service),
) -> TemplateResponse:
    template = await service.get_template_by_id(user_id, template_id)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template {template_id} not found"
        )
    return template


@router.delete("/{template_id}", status_code=status.HTTP_200_OK)
async def delete_template_endpoint(
    template_id: str,
    user_id: str = Depends(get_current_user_id),
    service: TemplateService = Depends(get_template_service),
) -> dict:
    success = await service.delete_template(user_id, template_id)
    if not success:
         raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template {template_id} not found or could not be deleted"
        )
    return {"message": "Template deleted successfully"}