
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from a2a_common.logging import get_logger
from a2a_common.utils import _call_mcp_tool, mcp_list_tools
from VLLM_Client.VLLMClient import VLLMClient

from .models import RagResultPayload, RagContextItem

logger = get_logger(__name__)
llm = VLLMClient()

MCP_BASE_URL = os.getenv("MCP_BASE_URL", "http://10.244.84.2:9000").rstrip("/")
MCP_ENDPOINT = f"{MCP_BASE_URL}/mcp"

DEFAULT_MAX_CHUNKS = int(os.getenv("RAG_MAX_CHUNKS", "5"))
MAX_TOOL_CALLS = 5

PER_ITEM_CHAR_BUDGET = int(os.getenv("RAG_PER_ITEM_CHAR_BUDGET", "1000"))
TOTAL_CHAR_BUDGET = int(os.getenv("RAG_TOTAL_CHAR_BUDGET", "5000"))

class RAGInput(BaseModel):
    user_id: str = Field(default="")
    transcript: str = Field(default="")

class ToolCall(BaseModel):
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)

def _extract_hits(mcp_result: Any) -> list[dict]:
    if isinstance(mcp_result, dict):
        sc = mcp_result.get("structuredContent")
        if isinstance(sc, dict):
            r = sc.get("result")
            if isinstance(r, list):
                return [x for x in r if isinstance(x, dict)]
            if isinstance(r, dict):
                return [r]

        r = mcp_result.get("result")
        if isinstance(r, list):
            return [x for x in r if isinstance(x, dict)]
        if isinstance(r, dict):
            return [r]

        for k in ("hits", "items", "documents", "docs", "results", "data", "reports"):
            v = mcp_result.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
            if isinstance(v, dict):
                return [v]

        c = mcp_result.get("content")
        if isinstance(c, list) and len(c) > 0:
            first = c[0]
            if isinstance(first, dict) and first.get("type") == "text":
                txt = first.get("text", "")
                try:
                    parsed = json.loads(txt)
                    if isinstance(parsed, dict):
                        return [parsed]
                    if isinstance(parsed, list):
                        return [x for x in parsed if isinstance(x, dict)]
                except Exception:
                    pass

    if isinstance(mcp_result, list):
        return [x for x in mcp_result if isinstance(x, dict)]

    return []

def _get_hit_score(hit: dict) -> Optional[float]:
    for k in ("score", "similarity", "rerank_score"):
        v = hit.get(k)
        if isinstance(v, (int, float)):
            return float(v)

    v = hit.get("distance")
    if isinstance(v, (int, float)):
        d = float(v)
        return 1.0 / (1.0 + max(d, 0.0))

    return None

def _pick_text(hit: Dict[str, Any]) -> str:
    for key in ("text", "content", "body", "chunk", "summary", "document", "payload", "snippet"):
        val = hit.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, dict):
            try:
                return json.dumps(val, ensure_ascii=False)
            except Exception:
                pass
    return ""

def _pick_title(hit: Dict[str, Any]) -> str:
    for key in ("title", "name"):
        val = hit.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""

def _pick_id(hit: Dict[str, Any]) -> str:
    for key in ("id", "uuid", "doc_id", "document_id", "report_id", "template_id"):
        val = hit.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""

def _truncate(s: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 3)] + "..."

def _tool_catalog_text(tools: list[Any], max_tools: int = 60) -> str:
    lines: List[str] = []
    for t in tools[:max_tools]:
        name = getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else None)
        if not isinstance(name, str) or not name.strip():
            continue
        desc = getattr(t, "description", None) or (t.get("description") if isinstance(t, dict) else None)
        schema = (
            getattr(t, "input_schema", None)
            or getattr(t, "inputSchema", None)
            or (t.get("inputSchema") if isinstance(t, dict) else None)
            or (t.get("input_schema") if isinstance(t, dict) else None)
        )

        props: List[str] = []
        if isinstance(schema, dict):
            p = schema.get("properties", {})
            if isinstance(p, dict):
                props = list(p.keys())[:20]

        d = (desc or "(no description)").strip()
        if len(d) > 160:
            d = d[:157] + "..."
        lines.append(f"- {name}: {d} | args={props if props else '(free-form)'}")

    if len(tools) > max_tools:
        lines.append(f"... (+{len(tools) - max_tools} weitere Tools)")
    return "\n".join(lines)

def _filter_args_by_schema(args: Dict[str, Any], schema: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not schema or not isinstance(schema, dict):
        return args
    props = schema.get("properties", {})
    if not isinstance(props, dict) or not props:
        return args
    return {k: v for k, v in args.items() if k in props}

def _schema_for_tool(tools: list[Any], tool_name: str) -> Optional[Dict[str, Any]]:
    for t in tools:
        name = getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else None)
        if name == tool_name:
            schema = (
                getattr(t, "input_schema", None)
                or getattr(t, "inputSchema", None)
                or (t.get("inputSchema") if isinstance(t, dict) else None)
                or (t.get("input_schema") if isinstance(t, dict) else None)
            )
            return schema if isinstance(schema, dict) else None
    return None

def _schema_allows(schema: Optional[Dict[str, Any]], key: str) -> bool:
    if not schema or not isinstance(schema, dict):
        return True
    props = schema.get("properties", {})
    if not isinstance(props, dict) or not props:
        return True
    return key in props

class ToolPlan(BaseModel):
    calls: List[ToolCall] = Field(default_factory=list)

def choose_tool_plan_with_llm(*, transcript: str, user_id: str, tools: list[Any], max_chunks: int) -> List[ToolCall]:
    catalog = _tool_catalog_text(tools)

    prompt = (
        "Du bist ein RAG-Planer für Bauberichte.\n"
        "Wähle passende MCP-Tools (0..3), um relevante Informationen für das Transkript zu finden.\n"
        "Achte besonders auf zeitliche Referenzen wie 'letzte Woche', 'davor', 'alter Bericht' und suche gezielt danach.\n"
        "Gib NUR valides JSON Format zurück. KEINE Kommentare.\n\n"
        "Regeln:\n"
        "- Maximal 3 Tools\n"
        "- Mindestens 1 Tool\n"
        "- Nutze user_id\n"
        "- Setze include_text=true wenn möglich\n"
        f"- Setze limit={max_chunks} (als Integer)\n\n"
        f"user_id: {user_id}\n"
        "Verfügbare Tools:\n"
        f"{catalog}\n\n"
        f"Transkript (Ausschnitte):\n{transcript[:4000]}\n\n"
    )

    try:
        plan = llm.generate_structured(
            response_model=ToolPlan,
            prompt=prompt,
            temperature=0.1, 
            max_tokens=360
        )
        calls = plan.calls
    except Exception as e:
        logger.warning(f"RAG planning failed: {e}")
        calls = []

    final_calls: List[ToolCall] = []
    for c in calls[:MAX_TOOL_CALLS]:
        name = c.name.strip()
        if not name: continue
        args = c.arguments or {}
        schema = _schema_for_tool(tools, name)
        if _schema_allows(schema, "user_id"):
            args["user_id"] = user_id
        if _schema_allows(schema, "include_text"):
            args["include_text"] = True
        if _schema_allows(schema, "limit"):
            args.setdefault("limit", max_chunks)
        final_calls.append(ToolCall(name=name, arguments=args))

    logger.info(f"tools to call {final_calls}")
    return final_calls[:MAX_TOOL_CALLS]

from a2a.server.agent_execution import RequestContext
from a2a_common.utils import get_artifact_from_context

async def retrieve_rag_payload(*, transcript: str, user_id: str) -> RagResultPayload:
    if not (user_id or "").strip() or not (transcript or "").strip():
        logger.info("RAG: missing user_id/transcript -> empty result")
        return RagResultPayload(context_documents=[])

    max_chunks = DEFAULT_MAX_CHUNKS

    try:
        tools = await mcp_list_tools(MCP_ENDPOINT)
        logger.info("RAG: tools discovered=%d", len(tools))
    except Exception as exc:
        logger.warning("RAG: mcp_list_tools failed: %s", exc, exc_info=True)
        return RagResultPayload(context_documents=[])

    if not tools:
        return RagResultPayload(context_documents=[])

    try:
        calls = choose_tool_plan_with_llm(transcript=transcript, user_id=user_id, tools=tools, max_chunks=max_chunks)
    except Exception as exc:
        logger.warning("RAG: planner failed: %s", exc, exc_info=True)
        calls = []

    if not calls:
        logger.warning("RAG: no planned tool calls")
        return RagResultPayload(context_documents=[])

    collected: List[Tuple[str, Dict[str, Any]]] = []
    for call in calls[:MAX_TOOL_CALLS]:
        try:
            logger.info(f"call mcp tool {call.name} with arguments{call.arguments}")
            res = await _call_mcp_tool(call.name, MCP_ENDPOINT, call.arguments)
            logger.info(f"result: {res}")
            hits = _extract_hits(res)
            logger.info(f"extract hit: {hits}")
            for h in hits:
                collected.append((call.name, h))
        except Exception as exc:
            logger.warning("RAG: tool call failed tool=%s err=%s", call.name, exc, exc_info=True)

    if not collected:
        return RagResultPayload(context_documents=[])

    def _score(item: Tuple[str, Dict[str, Any]]) -> float:
        s = _get_hit_score(item[1])
        return float(s) if isinstance(s, (int, float)) else 0.0

    collected.sort(key=_score, reverse=True)

    seen: set[str] = set()
    deduped: List[Tuple[str, Dict[str, Any]]] = []
    for tool_name, hit in collected:
        hid = _pick_id(hit)
        if not hid:
            try:
                hid = json.dumps(hit, sort_keys=True, ensure_ascii=False)[:160]
            except Exception:
                hid = str(id(hit))
        if hid in seen:
            continue
        seen.add(hid)
        deduped.append((tool_name, hit))
        if len(deduped) >= max_chunks:
            break

    items: List[RagContextItem] = []
    returned = 0

    for tool_name, hit in deduped:
        if returned >= max_chunks:
            break

        raw_text = _pick_text(hit)
        if not raw_text:
            continue

        doc_id = _pick_id(hit) or None
        title = _pick_title(hit) or None
        score = _get_hit_score(hit)

        snippet = _truncate(raw_text, PER_ITEM_CHAR_BUDGET)

        items.append(
            RagContextItem(
                id=doc_id,
                title=title,
                score=score,
                source_tool=tool_name,
                text=snippet,
            )
        )
        returned += 1

    logger.info("RAG: done returned_items=%d", returned)
    return RagResultPayload(context_documents=items)

async def retrieve_for_inputs(inputs: "RAGInputSchema") -> List[Dict[str, Any]]:
    from a2a_common.schemas.rag import RAGInput as RAGInputSchema
    result = await retrieve_rag_payload(
        transcript=inputs.transcript,
        user_id=inputs.user_id
    )
    return [d.model_dump() for d in result.context_documents]