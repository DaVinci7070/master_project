import logging
import anyio
import httpx
import json
from typing import Any, List, Dict
from app.models.api.report_models import (
    GenerateReportRequest, GenerateReportResponse,
    BatchUploadRequest, BatchUploadResponse, ReportResponse,
    PaginatedReportResponse, SubmitAnswersRequest
)
from app.adapters.orchestrator_adapter import OrchestratorAdapter
from app.repositories.qdrant_repository import QdrantReportsRepository
from app.adapters.sql_protocols import ReportRepositoryProtocol
from app.models.qdrant.qdrant_models import ReportRecord
from datetime import datetime
from app.core.security import hash_user_id
log = logging.getLogger("report-service")

from app.services.template_service import TemplateService

class ReportService:

    def __init__(
        self,
        orchestrator: OrchestratorAdapter,
        qdrant_repo: QdrantReportsRepository,
        postgres_repo: ReportRepositoryProtocol,
        template_service: TemplateService,
    ):
        self.orchestrator = orchestrator
        self.qdrant_repo = qdrant_repo
        self.postgres_repo = postgres_repo
        self.template_service = template_service

    async def _cleanup_failed_report(self, report_id: str, error: Exception):
        try:
            log.warning(f"Marking report {report_id} as failed due to: {error}")
            await self.postgres_repo.mark_as_failed(report_id, str(error))
        except Exception as cleanup_error:
            log.error(f"Failed to cleanup report {report_id}: {cleanup_error}")

    async def generate_report_from_transcript(
            self,
            user_id: str,
            request: GenerateReportRequest
    ) -> GenerateReportResponse:

        log.info(f"[PROCESS] user={user_id}")

        processing_report = await self.postgres_repo.save_report_as_draft(
            user_id=user_id,
            report_content="",
            report_format="text",
            title="Sitzung wird verarbeitet...",
            fields={},
            tags=[],
            original_transcript=request.transcript,
            location=None,
            event_time=None,
            status="waiting_for_input"
        )
        report_id = str(processing_report.id)
        try:
            if request.run_id and request.answers is not None:
                log.info(f"[RESUME] Resuming orchestration with run_id={request.run_id}")
                orchestrator_response = await self.orchestrator.submit_answers(
                    run_id=request.run_id,
                    user_id=user_id,
                    transcript=request.transcript,
                    answers=request.answers,
                    answer_transcript=request.answer_transcript if hasattr(request, "answer_transcript") else None
                )
            else:
                resolved_template_id = await self.template_service.get_template_or_fallback(
                    user_id=user_id, 
                    template_id=request.template_id
                )
                orchestrator_response = await self.orchestrator.process_transcript(
                    user_id=user_id,
                    transcript=request.transcript,
                    template_id=resolved_template_id,
                )
            return await self._handle_orchestrator_result(user_id, orchestrator_response, existing_report_id=report_id)

        except Exception as e:
            log.error(f"[PROCESS] ❌ Error: {e}", exc_info=True)
            await self._cleanup_failed_report(report_id, e)
            raise e

    async def resume_orchestration_with_answers(self, user_id: str, request: SubmitAnswersRequest) -> GenerateReportResponse:
        log.info(f"[RESUME] run_id={request.run_id}")
        try:

            existing_report = await self.postgres_repo.get_report_by_run_id(str(request.run_id))
            existing_report_id = str(existing_report.id) if existing_report else None
            
            if existing_report_id:
                log.info(f"[RESUME] Found existing report {existing_report_id} for run_id={request.run_id}")
            else:
                log.warning(f"[RESUME] No existing report found for run_id={request.run_id}")

            orchestrator_response = await self.orchestrator.submit_answers(
                run_id=request.run_id,
                user_id=user_id,
                transcript="", 
                answers=request.answers,
                answer_transcript=request.answer_transcript
            )
            return await self._handle_orchestrator_result(user_id, orchestrator_response, existing_report_id=existing_report_id)
        except Exception as e:
            log.error(f"[RESUME] ❌ Error: {e}", exc_info=True)
            raise e

    async def _handle_orchestrator_result(self, user_id: str, orchestrator_response: Dict[str, Any], existing_report_id: str = None) -> GenerateReportResponse:
        if orchestrator_response.get("status") == "waiting_for_user":
            run_id = orchestrator_response.get("run_id")
            

            if existing_report_id and run_id:
                try:
                    report = await self.postgres_repo.get_report_by_id(existing_report_id)
                    if report:
                        meta = report.report_metadata or {}
                        meta["run_id"] = run_id
                        await self.postgres_repo.update_draft(
                            report_id=existing_report_id,
                            report_content=report.report_content,  
                            report_format=report.report_format,
                            metadata=meta
                        )
                        log.info(f"[PROCESS] Linked run_id={run_id} to report={existing_report_id}")
                except Exception as e:
                    log.error(f"[PROCESS] Failed to link run_id to report: {e}")

            return GenerateReportResponse(
                status="waiting_for_user",
                run_id=run_id,
                report_id=existing_report_id if existing_report_id else None,
                questions=orchestrator_response.get("questions", [])
            )

        final_report_raw = (
            orchestrator_response.get("report")
            or orchestrator_response.get("report_json")
            or orchestrator_response.get("final_report")
        )

        if final_report_raw is None:
             raise ValueError("Orchestrator returned no valid report.")

        report_content: str = ""
        report_format: str = "text"
        title: str = None
        fields: dict = {}
        tags: List[str] = []
        original_transcript: str = None
        location: str = None
        event_time: str = None

        if isinstance(final_report_raw, dict):
            if "content" in final_report_raw and isinstance(final_report_raw["content"], str):
                 report_format = "text"
                 report_content = final_report_raw["content"]
                 title = final_report_raw.get("title")
                 tags = final_report_raw.get("tags", [])
                 original_transcript = final_report_raw.get("original_transcript")
                 location = final_report_raw.get("location")
                 event_time = final_report_raw.get("time")
            else:
                 report_format = "json"
                 report_content = json.dumps(final_report_raw, ensure_ascii=False)
                 title = final_report_raw.get("title")
                 fields = final_report_raw.get("fields", {})
                 tags = final_report_raw.get("tags", [])
                 original_transcript = final_report_raw.get("original_transcript")
                 location = final_report_raw.get("location")
                 event_time = final_report_raw.get("time")
        else:
            try:
                parsed = json.loads(str(final_report_raw))
                if isinstance(parsed, dict):
                    if "content" in parsed and isinstance(parsed["content"], str):
                        report_format = "text"
                        report_content = parsed["content"]
                        title = parsed.get("title")
                        tags = parsed.get("tags", [])
                        original_transcript = parsed.get("original_transcript")
                        location = parsed.get("location")
                        event_time = parsed.get("time")
                    else:
                        report_format = "json"
                        report_content = json.dumps(parsed, ensure_ascii=False)
                        title = parsed.get("title")
                        fields = parsed.get("fields", {})
                        tags = parsed.get("tags", [])
                        original_transcript = parsed.get("original_transcript")
                        location = parsed.get("location")
                        event_time = parsed.get("time")
                else:
                    raise json.JSONDecodeError("Not a dict", "", 0)
            except json.JSONDecodeError:
                report_format = "text"
                report_content = str(final_report_raw)
                lines = report_content.strip().split('\n')
                if lines and lines[0].startswith('# '):
                    title = lines[0][2:].strip()
                else:
                    title = "Generierter Bericht"

        if existing_report_id:
            saved_report = await self.postgres_repo.update_draft(
                report_id=existing_report_id,
                report_content=report_content,
                report_format=report_format,
                title=title,
                fields=fields,
                tags=tags,
                original_transcript=original_transcript,
                location=location,
                event_time=event_time,
                status="pending_review"
            )
        else:
             saved_report = await self.postgres_repo.save_report_as_draft(
                user_id=user_id,
                report_content=report_content,
                report_format=report_format,
                title=title,
                fields=fields,
                tags=tags,
                original_transcript=original_transcript,
                location=location,
                event_time=event_time,
                status="pending_review"
            )

        log.info(
            f"[PROCESS] ✅ Report validiert/erzeugt: report_id={saved_report.id}"
        )

        return GenerateReportResponse(
            report_id=str(saved_report.id),
            status=saved_report.status,
            report_content=saved_report.report_content,
            report_format=saved_report.report_format,
            title=saved_report.title,
            tags=saved_report.tags,
            original_transcript=saved_report.original_transcript,
            location=saved_report.location,
            time=saved_report.event_time.isoformat() if hasattr(saved_report.event_time, 'isoformat') else str(saved_report.event_time) if saved_report.event_time else None
        )

    async def get_user_reports(self, user_id: str, skip: int, limit: int) -> PaginatedReportResponse:
        db_reports, total = await self.postgres_repo.get_reports_by_user(user_id, skip, limit)

        items = [
            ReportResponse(
                report_id=str(r.id),
                user_id=user_id,
                summary=str(r.report_content),
                status=r.status,
                tags=r.tags or [],
                title=r.title or "No Title",
                original_transcript=r.original_transcript,
                location=r.location,
                time=r.event_time
            )
            for r in db_reports
        ]

        return PaginatedReportResponse(
            items=items,
            total=total,
            skip=skip,
            limit=limit
        )

    async def store_reports_batch(self, user_id: str, data: BatchUploadRequest) -> BatchUploadResponse:
        log.info(f"[BATCH_UPLOAD] user={user_id}, count={len(data.reports)}")

        await anyio.to_thread.run_sync(
            self.qdrant_repo.ensure_user_collection,
            user_id
        )

        records = [
            ReportRecord(
                user_id=user_id,
                report_id=r.report_id,
                text=r.text,
                fields=r.fields,
                title=r.title,
                created_at=r.created_at or datetime.utcnow().isoformat(),
                created_at_ts=int(datetime.utcnow().timestamp()),
                tags=r.tags,
                source=r.source or "batch_upload",
                metadata=r.metadata,
                original_transcript=r.original_transcript,
                location=r.location,
                time=r.time,
            )
            for r in data.reports
        ]

        result = self.qdrant_repo.upsert_reports_batch(
            user_id=user_id,
            reports=records
        )

        log.info(f"[BATCH_UPLOAD] ✅ Upserted {result.upserted} reports")

        return BatchUploadResponse(
            user_collection=result.user_collection,
            upserted=result.upserted,
            ids=result.ids,
        )

    async def finalize_report(self, report_id: str, user_id: str) -> ReportResponse:
        report_id = report_id.lower()

        hashed_id = hash_user_id(user_id)
        report = await self.postgres_repo.get_report_by_id(report_id)
        if not report:
             raise ValueError(f"Report with id={report_id} not found.")
        if report.hashed_user_id != hashed_id:
             raise PermissionError(f"User {user_id} is not authorized to finalize report {report_id}.")

        finalized_report = await self.postgres_repo.finalize_report(report_id)
        if not finalized_report:
             raise ValueError(f"Report with id={report_id} could not be finalized.")

        log.info(f"[FINALIZE] Report id={report_id} finalized in SQL. Syncing to Qdrant...")

        await anyio.to_thread.run_sync(
            self.qdrant_repo.ensure_user_collection,
            user_id
        )

        record = ReportRecord(
            user_id=user_id,
            report_id=str(finalized_report.id),
            text=str(finalized_report.report_content),
            fields=finalized_report.fields or {},
            title=finalized_report.title or "Untitled Report",
            created_at=finalized_report.created_at.isoformat() if finalized_report.created_at else datetime.utcnow().isoformat(),
            created_at_ts=int(finalized_report.created_at.timestamp()) if finalized_report.created_at else int(datetime.utcnow().timestamp()),
            tags=finalized_report.tags or [],
            source="finalized_draft",
            metadata=finalized_report.report_metadata or {"status": "confirmed"},
            original_transcript=finalized_report.original_transcript,
            location=finalized_report.location,
            time=finalized_report.event_time
        )

        await anyio.to_thread.run_sync(
            self.qdrant_repo.upsert_reports_batch,
            user_id,
            [record]
        )
        log.info(f"[FINALIZE] ✅ Report id={report_id} synced to Qdrant.")

        return ReportResponse(
            report_id=str(finalized_report.id),
            user_id=user_id,
            summary=str(finalized_report.report_content),
            status=finalized_report.status,
            tags=finalized_report.tags or [],
            title=finalized_report.title or "No Title",
            original_transcript=finalized_report.original_transcript,
            location=finalized_report.location,
            time=finalized_report.event_time
        )

    async def delete_report(self, user_id: str, report_id: str) -> dict:
        report_id = report_id.lower()
        hashed_id = hash_user_id(user_id)
        report = await self.postgres_repo.get_report_by_id(report_id)
        if not report:
             raise ValueError(f"Report with id={report_id} not found.")
        if report.hashed_user_id != hashed_id:
             raise PermissionError(f"User {user_id} is not authorized to delete report {report_id}.")

        deleted_sql = await self.postgres_repo.delete_report(report_id)
        if not deleted_sql:
             log.warning(f"Report {report_id} could not be deleted from SQL (maybe concurrent delete?)")

        await anyio.to_thread.run_sync(
            self.qdrant_repo.delete_report,
            user_id,
            report_id
        )
        log.info(f"[DELETE] ✅ Report id={report_id} deleted from SQL and Qdrant.")
        return {"id": report_id, "status": "deleted"}
