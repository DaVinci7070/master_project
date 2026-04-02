from typing import Protocol, List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sql.sql_models import Report

class ReportRepositoryProtocol(Protocol):

    async def save_report_as_draft(
        self, 
        user_id: str, 
        report_content: str, 
        report_format: str,
        title: str = None,
        fields: dict = None,
        tags: list = None,
        metadata: dict = None
    ) -> Report:
        ...

    async def get_report_by_id(
        self, report_id: str
    ) -> Optional[Report]:
        ...

    async def get_reports_by_user(
        self, user_id: str, skip: int = 0, limit: int = 100
    ) -> tuple[List[Report], int]:
        ...

    async def update_report(
        self, report_id: str, report_json: Dict[str, Any]
    ) -> Optional[Report]:
        ...

    async def finalize_report(
        self, report_id: str
    ) -> Optional[Report]:
        ...

    async def delete_report(
        self, report_id: str
    ) -> bool:
        ...

    async def mark_as_failed(
        self, report_id: str, error_message: str
    ) -> None:
        ...

    async def update_draft(
        self,
        report_id: str,
        report_content: str,
        report_format: str,
        title: str = None,
        fields: dict = None,
        tags: list = None,
        metadata: dict = None,
        original_transcript: str = None,
        location: str = None,
        event_time: str = None
    ) -> Report:
        ...