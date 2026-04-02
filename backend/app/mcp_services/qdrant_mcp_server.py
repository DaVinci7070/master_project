import os
import logging
import anyio
from typing import List, Optional, Dict
from pydantic import BaseModel, Field
import json
from mcp.server.fastmcp import FastMCP
from app.repositories.qdrant_repository import get_reports_store
from app.models.qdrant.qdrant_models import TemplateHit
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from app.adapters.qdrant.reports_ports import ReportsIndex
from app.adapters.qdrant.templates_port import TemplatesIndex

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
log = logging.getLogger("qdrant-reports-mcp_services")

mcp = FastMCP("qdrant-mcp_services-server", json_response=True, host="0.0.0.0", port=9000, stateless_http=True,)

reportStore = get_reports_store()
reports: ReportsIndex = reportStore
templates: TemplatesIndex = reportStore

class SearchHitOut(BaseModel):
    id: str
    score: float
    report_id: Optional[str] = None
    title: Optional[str] = None
    created_at: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    source: Optional[str] = None
    snippet: Optional[str] = None
    text: Optional[str] = None
    metadata: dict = Field(default_factory=dict)

class DocumentStats(BaseModel):
    total_documents: int
    by_tag: Dict[str, int] = Field(default_factory=dict)
    date_range: Optional[Dict[str, str]] = None

@mcp.tool()
async def search_reports(
        user_id: str,
        query: str,
        limit: int = 5,
        include_text: bool = False
) -> List[SearchHitOut]:
    log.info(f"[SEARCH] user={user_id}, query='{query}', limit={limit}")

    hits = await anyio.to_thread.run_sync(
        lambda: reports.search(user_id, query, limit=limit, include_text=include_text)
    )
    log.info(f"[SEARCH] Found {len(hits)} results")
    return [SearchHitOut(**h.__dict__) for h in hits]

@mcp.tool()
async def search_by_tags(
        user_id: str,
        tags: List[str],
        limit: int = 10,
        include_text: bool = False
) -> List[SearchHitOut]:
    log.info(f"[TAG_SEARCH] user={user_id}, tags={tags}, limit={limit}")
    hits = await anyio.to_thread.run_sync(
        lambda: reports.search_by_tags(user_id, tags, limit=limit, include_text=include_text)
    )
    return [SearchHitOut(**h.__dict__) for h in hits]

@mcp.tool()
async def search_by_date_range(
        user_id: str,
        start_date: str,
        end_date: str,
        limit: int = 10,
        include_text: bool = False
) -> List[SearchHitOut]:
    log.info(f"[DATE_SEARCH] user={user_id}, range={start_date} to {end_date}")
    hits = await anyio.to_thread.run_sync(
        lambda: reports.search_by_date_range(user_id, start_date, end_date, limit=limit, include_text=include_text)
    )
    return [SearchHitOut(**h.__dict__) for h in hits]

@mcp.tool()
async def get_report_by_id(
        user_id: str,
        report_id: str,
        include_text: bool = True
) -> Optional[SearchHitOut]:
    log.info(f"[GET_BY_ID] user={user_id}, report_id={report_id}")
    hit = await anyio.to_thread.run_sync(
        lambda: reports.get_by_id(user_id, report_id, include_text=include_text)
    )
    return SearchHitOut(**hit.__dict__) if hit else None


@mcp.tool()
async def get_user_stats(user_id: str) -> DocumentStats:
    log.info(f"[STATS] user={user_id}")
    stats = await anyio.to_thread.run_sync(reports.get_user_stats, user_id)
    return DocumentStats(**stats)

@mcp.tool()
async def multi_query_search(
    user_id: str,
    queries: List[str],
    limit: int = 3,
    include_text: bool = False
) -> Dict[str, List[SearchHitOut]]:
    log.info(f"[MULTI_QUERY] user={user_id}, queries={len(queries)}")

    results: Dict[str, List[SearchHitOut]] = {}
    lock = anyio.Lock()

    async def run_one(q: str) -> None:
        hits = await anyio.to_thread.run_sync(
            lambda: reports.search(user_id, q, limit=limit, include_text=include_text)
        )
        out = [SearchHitOut(**h.__dict__) for h in hits]
        async with lock:
            results[q] = out

    async with anyio.create_task_group() as tg:
        for q in queries:
            tg.start_soon(run_one, q)

    return results

def _tpl_hit_to_out(h: TemplateHit, include_text: bool) -> SearchHitOut:
    text: Optional[str] = None
    if include_text and h.content is not None:
        text = json.dumps(h.content, ensure_ascii=False)

    return SearchHitOut(
        id=h.id,
        score=h.score,
        title=h.name,
        tags=h.tags or [],
        snippet=h.snippet,
        text=text,
        metadata=h.metadata or {},
    )

@mcp.tool()
async def search_templates(
    user_id: str,
    query: str,
    limit: int = 5,
    include_text: bool = True,
) -> List[SearchHitOut]:

    log.info("[TPL_SEARCH] user_id=%s limit=%s", user_id, limit)

    hits: List[TemplateHit] = await anyio.to_thread.run_sync(
        lambda: templates.search_templates(
            user_id=user_id,
            query=query,
            limit=limit,
            include_text=include_text,
        )
    )

    return [_tpl_hit_to_out(h, include_text) for h in hits]

@mcp.tool()
async def get_template_by_id(
    user_id: str,
    template_id: str,
    include_text: bool = True,
) -> Optional[SearchHitOut]:
    log.info(f"[TPL_GET_BY_ID] user_id={user_id}, template_id={template_id}")
    hit = await anyio.to_thread.run_sync(
        lambda: templates.get_template_by_id(user_id, template_id)
    )
    log.info(f"Found Template hit={hit}")
    return _tpl_hit_to_out(hit, include_text) if hit else None

@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")

def main() -> None:
    log.info("=" * 60)
    log.info("Starting Qdrant-Database MCP Server for Report Management")
    log.info(f"Host: 0.0.0.0")
    log.info(f"Port: 9000")
    log.info(f"Qdrant URL: {os.getenv('QDRANT_URL', 'NOT SET')}")
    log.info("=" * 60)

    try:
        mcp.run(transport="streamable-http")

    except Exception as e:
        log.error(f"Failed to start server: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    main()
