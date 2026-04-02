
from __future__ import annotations

import json
import uuid
from typing import Optional, Any, Tuple, Dict, List, Literal

import httpx
from a2a.server.agent_execution import RequestContext
from a2a.types import Message, Task, Part, TextPart, DataPart
from pydantic import BaseModel

def safe_json_parse(text: str, fallback: Any = None) -> Any:
    if not text:
        return fallback

    text = text.strip()

    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
        else:
            text = "\n".join(lines[1:]).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return fallback

    return fallback

def get_input_envelope_and_text_from_context(
    context: RequestContext,
) -> Tuple[Optional[Dict[str, Any]], str]:
    if not context.message:
        return None, ""

    envelope: Optional[Dict[str, Any]] = None
    transcript_parts: list[str] = []

    for part in context.message.parts or []:
        root = part.root

        if isinstance(root, DataPart) and isinstance(root.data, dict):
            if envelope is None:
                envelope = root.data

            t = root.data.get("transcript")
            if isinstance(t, str) and t.strip():
                transcript_parts.append(t.strip())

        elif isinstance(root, TextPart) and root.text:
            text_content = root.text.strip()
            parsed = safe_json_parse(text_content)
            if isinstance(parsed, dict) and not envelope:
                envelope = parsed
                if "transcript" in parsed and isinstance(parsed["transcript"], str):
                     transcript_parts.append(parsed["transcript"].strip())
            else:
                transcript_parts.append(text_content)

    transcript = " ".join(transcript_parts).strip()
    return envelope, transcript

def get_user_text_from_context(context: RequestContext) -> str:
    _envelope, transcript = get_input_envelope_and_text_from_context(context)
    return transcript

def extract_text_from_result(root: Any) -> str:
    result = getattr(root, "result", root)

    if isinstance(result, Message):
        return extract_text_from_message(result) or ""

    if isinstance(result, Task):
        return extract_text_from_task(result) or ""

    return ""

def extract_text_from_message(message: Message) -> Optional[str]:
    texts: list[str] = []
    for part in message.parts or []:
        if isinstance(part.root, TextPart):
            if part.root.text:
                texts.append(part.root.text)

    return "\n".join(texts).strip() or None

def extract_text_from_task(task: Task) -> Optional[str]:
    if not task.artifacts:
        return None

    collected: list[str] = []

    for artifact in task.artifacts:
        for part in artifact.parts or []:
            text = extract_text_from_part(part)
            if text:
                collected.append(text)

    return "\n".join(collected).strip() or None

def extract_text_from_part(part: Part) -> Optional[str]:
    root = part.root
    if isinstance(root, TextPart):
        return root.text or ""
    return None

def get_artifact_from_context(context: RequestContext, hint: str, fallback: Any = None) -> Any:
    if not context.message or not context.message.parts:
        return fallback

    for part in context.message.parts:
        root = part.root
        if isinstance(root, DataPart) and isinstance(root.data, dict):
            if root.data.get("_slot") == hint:
                return root.data.get("value")

        if isinstance(root, DataPart) and root.data and isinstance(root.data, dict):
            metadata = root.data.get("_metadata", {})
            if metadata.get("hint") == hint or metadata.get("key") == hint:
                return root.data.get("value")
            if hint in root.data:
                return root.data[hint]

    envelope, _ = get_input_envelope_and_text_from_context(context)
    if envelope and hint in envelope:
        return envelope[hint]

    return fallback

def create_signal_response(signal_type: Literal["SUSPEND", "CONTINUE", "SUCCESS", "ERROR"], 
                           data: Optional[Dict[str, Any]] = None,
                           reason: Optional[str] = None) -> Dict[str, Any]:
    return {
        "_metadata": {"type": "signal"},
        "signal": signal_type,
        "reason": reason,
        "data": data or {}
    }

def get_signal_from_result(result_parts: List[Any]) -> Optional[Dict[str, Any]]:
    for part in result_parts:
        root = getattr(part, "root", part)
        if hasattr(root, "data") and isinstance(root.data, dict):
            if root.data.get("_metadata", {}).get("type") == "signal":
                return root.data
        if hasattr(root, "text") and root.text:
            parsed = safe_json_parse(root.text)
            if isinstance(parsed, dict) and parsed.get("_metadata", {}).get("type") == "signal":
                return parsed

        elif isinstance(root, dict) and root.get("_metadata", {}).get("type") == "signal":
            return root
    return None

async def _call_mcp_tool(name: str, mcp_endpoint: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "jsonrpc": "2.0",
        "id": "template-loader",
        "method": "tools/call",
        "params": {
            "name": name,
            "arguments": arguments,
        },
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(mcp_endpoint, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data.get("result")

class ToolSpec(BaseModel):
    name: str
    description: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None

async def mcp_list_tools(mcp_http_endpoint: str) -> list[ToolSpec]:
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tools/list",
        "params": {},
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            mcp_http_endpoint,
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        tools_raw = (data.get("result") or {}).get("tools") or []
        tools: list[ToolSpec] = []
        for t in tools_raw:
            if not isinstance(t, dict):
                continue
            tools.append(
                ToolSpec(
                    name=t.get("name", ""),
                    description=t.get("description"),
                    input_schema=t.get("inputSchema") or t.get("input_schema"),
                )
            )
        return tools