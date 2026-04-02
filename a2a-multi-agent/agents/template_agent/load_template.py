
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from a2a_common.logging import get_logger
from VLLM_Client.VLLMClient import VLLMClient
from a2a_common.utils import _call_mcp_tool
from agents.template_agent.models import TemplateResult

logger = get_logger(__name__)

MCP_BASE_URL = os.getenv("MCP_BASE_URL", "http://10.244.84.2:9000")
MCP_ENDPOINT = f"{MCP_BASE_URL}/mcp"

llm = VLLMClient()
TEMPLATE_MIN_SCORE = float(os.getenv("TEMPLATE_MIN_SCORE", "0.75"))

async def _search_template_semantic(user_id: str, query: str) -> Optional[Dict[str, Any]]:
    if not (user_id or "").strip(): return None
    try:
        arguments = {"user_id": user_id, "query": query or "generic", "limit": 1, "include_text": True}
        result = await _call_mcp_tool("search_templates", MCP_ENDPOINT, arguments)
        hits = _extract_hits(result)
        if not hits: return None
        hit = hits[0]
        template_id = str(hit.get("id") or "")
        text_or_obj = hit.get("text") or hit.get("content") or ""
        content = text_or_obj if isinstance(text_or_obj, dict) else (json.loads(text_or_obj) if isinstance(text_or_obj, str) and text_or_obj.strip().startswith("{") else {})
        return {"template_id": template_id, "template_name": hit.get("title") or template_id, "template": content, "score": hit.get("score") or 0.0}
    except Exception as e:
        logger.warning(f"MCP search failed: {e}")
        return None

def _extract_hits(mcp_result: Any) -> list[dict]:
    if isinstance(mcp_result, dict):
        if "content" in mcp_result and isinstance(mcp_result["content"], list):
            for part in mcp_result["content"]:
                if isinstance(part, dict) and part.get("type") == "text":
                    try: return _extract_hits(json.loads(part.get("text")))
                    except: continue
        r = mcp_result.get("result") or mcp_result.get("hits") or mcp_result.get("items")
        if isinstance(r, list): return [x for x in r if isinstance(x, dict)]
        if "id" in mcp_result: return [mcp_result]
    return mcp_result if isinstance(mcp_result, list) else []

async def _infer_template_query(transcript: str) -> str:
    prompt = f"Erzeuge eine kurze Suchanfrage für ein Bericht-Template.\n\nTranskript:\n{transcript[:1000]}\n\nSuchanfrage:"
    try: return llm.generate(prompt, temperature=0.0, max_tokens=50).strip() or "generic"
    except: return "generic"

async def _get_template_by_id(user_id: str, template_id: str) -> Optional[Dict[str, Any]]:
    try:
        args = {"user_id": user_id, "template_id": template_id, "include_text": True}
        res = await _call_mcp_tool("get_template_by_id", MCP_ENDPOINT, args)
        if not res: return None
        tcontent = res.get("template") or res.get("content") or res.get("text") or res
        return {"template_id": template_id, "template_name": res.get("title") or template_id, "template": tcontent if isinstance(tcontent, dict) else {}, "score": 1.0}
    except: return None

def _load_default_template() -> Optional[Dict[str, Any]]:
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        default_path = os.path.join(current_dir, "defaults", "construction_report.json")
        if os.path.exists(default_path):
            with open(default_path, "r", encoding="utf-8") as f:
                content = json.load(f)
            return {
                "template_id": "system_default",
                "template_name": content.get("name", "Default Template"),
                "template": content,
                "score": 0.1
            }
    except Exception as e:
        logger.error(f"Failed to load default template: {e}")
    return None

async def load_template_for_payload(*, transcript: str, user_id: str, template_id: Optional[str] = None) -> TemplateResult:
    if not user_id or not transcript: return TemplateResult()
    found = await _get_template_by_id(user_id, template_id) if template_id else None
    if not found:
        query = await _infer_template_query(transcript)
        found = await _search_template_semantic(user_id, query)
    if not found or found.get("score", 0) < (0.0 if template_id else TEMPLATE_MIN_SCORE):
        logger.info("No suitable template found, loading default.")
        found = _load_default_template()
        
    if not found:
        return TemplateResult()

    return TemplateResult(template_id=found["template_id"], template_name=found["template_name"], template=found["template"], score=float(found["score"]))