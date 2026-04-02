import logging
from typing import List, Dict, Any, Optional
import json
from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sql.sql_models import Report
from app.core.security import hash_user_id

log = logging.getLogger(__name__)

class PostgresRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_report_as_draft(
            self,
            user_id: str,
            report_content: str,
            report_format: str,
            title: str = None,
            fields: dict = None,
            tags: list = None,
            metadata: dict = None,
            original_transcript: str = None,
            location: str = None,
            event_time: str = None,
            status: str = "pending_review",
    ) -> Report:

        hashed_id = hash_user_id(user_id)
        log.info(f"Saving new draft report for hashed_user_id '{hashed_id[:8]}...'")

        if report_format not in {"json", "text"}:
            raise ValueError(f"Invalid report_format={report_format!r}. Expected 'json' or 'text'.")

        if report_format == "json":
            try:
                json.loads(report_content)
            except json.JSONDecodeError as e:
                raise ValueError("report_format='json' but report_content is not valid JSON.") from e

        db_report = Report(
            hashed_user_id=hashed_id,
            report_content=report_content,
            report_format=report_format,
            status=status,
            is_editable=True,
            title=title,
            fields=fields or {},
            tags=tags or [],
            report_metadata=metadata or {},
            original_transcript=original_transcript,
            location=location,
            event_time=event_time,
        )
        self.session.add(db_report)
        await self.session.commit()
        await self.session.refresh(db_report)
        return db_report

    async def get_report_by_id(
        self, report_id: str
    ) -> Optional[Report]:

        log.info(f"Fetching report with id={report_id}")
        result = await self.session.execute(select(Report).where(Report.id == report_id))
        return result.scalar_one_or_none()

    async def get_report_by_run_id(
        self, run_id: str
    ) -> Optional[Report]:
        log.info(f"Fetching report with run_id={run_id}")

        stmt = select(Report).where(
            func.json_extract_path_text(Report.report_metadata, 'run_id') == run_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_reports_by_user(
        self, user_id: str, skip: int = 0, limit: int = 100
    ) -> tuple[List[Report], int]:
        from sqlalchemy import func

        hashed_id = hash_user_id(user_id)
        log.info(f"Fetching reports for hashed_user_id '{hashed_id[:8]}...' with limit={limit}, skip={skip}")

        count_stmt = (
            select(func.count())
            .select_from(Report)
            .where(
                Report.hashed_user_id == hashed_id,
                Report.status != "waiting_for_input"
            )
        )
        count_result = await self.session.execute(count_stmt)
        total_count = count_result.scalar() or 0

        stmt = (
            select(Report)
            .where(
                Report.hashed_user_id == hashed_id,
                Report.status != "waiting_for_input"
            )
            .offset(skip)
            .limit(limit)
            .order_by(Report.created_at.desc())
        )
        result = await self.session.execute(stmt)
        reports = list(result.scalars().all())

        return reports, total_count

    async def update_report(
        self, report_id: str, report_json: Dict[str, Any]
    ) -> Optional[Report]:

        log.info(f"Attempting to update report id={report_id}")
        report = await self.get_report_by_id(report_id)

        if not report:
            log.warning(f"Update failed: Report with id={report_id} not found.")
            return None

        if not report.is_editable:
            log.warning(f"Update failed: Report with id={report_id} is finalized and not editable.")
            return None

        report.report_content = report_json
        await self.session.commit()
        await self.session.refresh(report)
        log.info(f"Successfully updated report id={report_id}")
        return report

    async def finalize_report(
        self, report_id: str
    ) -> Optional[Report]:
        log.info(f"Finalizing report id={report_id}")
        stmt = update(Report).where(Report.id == report_id).values(status="confirmed", is_editable=False).returning(Report)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one_or_none()

    async def delete_report(self, report_id: str) -> bool:
        log.info(f"Deleting report id={report_id}")
        stmt = delete(Report).where(Report.id == report_id)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def mark_as_failed(self, report_id: str, error_message: str) -> None:
        log.warning(f"Marking report {report_id} as failed: {error_message}")
        stmt = (
            update(Report)
            .where(Report.id == report_id)
            .values(
                status="failed",
                report_metadata=func.jsonb_set(
                    Report.report_metadata, 
                    '{error}',
                    f'"{error_message}"' 
                ) 
            )
        )
        stmt = update(Report).where(Report.id == report_id).values(status="failed")
        await self.session.execute(stmt)
        await self.session.commit()

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
        event_time: str = None,
        status: str = None
    ) -> Report:
        log.info(f"Updating draft report {report_id}")
        stmt = (
            update(Report)
            .where(Report.id == report_id)
            .values(
                report_content=report_content,
                report_format=report_format,
                status=status if status is not None else Report.status, 
                title=title if title is not None else Report.title,
                fields=fields if fields is not None else Report.fields,
                tags=tags if tags is not None else Report.tags,
                report_metadata=metadata if metadata is not None else Report.report_metadata,
                original_transcript=original_transcript if original_transcript is not None else Report.original_transcript,
                location=location if location is not None else Report.location,
                event_time=event_time if event_time is not None else Report.event_time,
                updated_at=func.now()
            )
            .returning(Report)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        report = result.scalar_one_or_none()
        if not report:
             raise ValueError(f"Report {report_id} not found for update.")
        return report
