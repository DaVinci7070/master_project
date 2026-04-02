import logging
import uuid
from typing import Dict, Any, Optional
import json
import httpx
from app.core.exceptions import AgentResponseError, OrchestrationError

log = logging.getLogger("orchestrator-adapter")

class OrchestratorAdapter:

    def __init__(self, base_url: str = "http://10.244.84.3:8000", timeout: float = 180.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)

    async def process_transcript(self, user_id: str, transcript: str, template_id: Optional[str] = None) -> Dict[str, Any]:
        return await self._send_to_orchestrator({
            "user_id": user_id,
            "transcript": transcript,
            "template_id": template_id,
        }, transcript)

    async def submit_answers(self, run_id: str, user_id: str, transcript: str, answers: Dict[str, Any], answer_transcript: Optional[str] = None) -> Dict[str, Any]:
        return await self._send_to_orchestrator({
            "run_id": str(run_id),
            "user_id": user_id,
            "answers": answers,
            "answer_transcript": answer_transcript
        }, transcript)

    async def _send_to_orchestrator(self, input_data: Dict[str, Any], transcript: str) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": f"backend-orch-{uuid.uuid4().hex[:8]}",
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": f"msg-{uuid.uuid4().hex[:8]}",
                    "role": "user",
                    "parts": [
                        {
                            "kind": "data",
                            "type": "input_envelope",
                            "data": input_data,
                        }
                    ],
                }
            },
        }
        if transcript:
            payload["params"]["message"]["parts"].append({
                "kind": "text",
                "text": transcript
            })

        url = self.base_url
        log.info("[ORCHESTRATOR] Sending request data=%s", list(input_data.keys()))

        try:
            resp = await self.client.post(url, json=payload)
            resp.raise_for_status()
        except httpx.TimeoutException as e:
            log.error(f"[ORCHESTRATOR] Timeout: {e}")
            raise AgentResponseError(message="Orchestrator timeout", details={"error": str(e)}) from e
        except httpx.HTTPStatusError as e:
            log.error(f"[ORCHESTRATOR] HTTP Error: {e}")
            raise OrchestrationError(message=f"Orchestrator HTTP {e.response.status_code}", details={"error": str(e)}, should_retry=True) from e
        except httpx.RequestError as e:
            log.error(f"[ORCHESTRATOR] Connection Error: {e}")
            raise OrchestrationError(message="Orchestrator connection failed", details={"error": str(e)}, should_retry=True) from e

        jsonrpc = resp.json()
        if isinstance(jsonrpc, dict) and "error" in jsonrpc:
            err = jsonrpc.get("error") or {}
            msg = err.get('message') or str(err)
            log.error(f"[ORCHESTRATOR] JSON-RPC Error: {msg}")
            raise AgentResponseError(message=f"Agent Error: {msg}", details=err)

        result = (jsonrpc or {}).get("result") or {}
        parts = result.get("parts") or []

        for part in parts:
            if isinstance(part, dict) and part.get("kind") == "text":
                text = part.get("text")
                if isinstance(text, str):
                    try:
                        data = json.loads(text)
                        if isinstance(data, dict):
                            if data.get("type") == "orchestration_suspended":
                                return {
                                    "status": "waiting_for_user",
                                    "run_id": data.get("run_id"),
                                    "questions": data.get("questions", [])
                                }
                            return {"report_json": data}
                    except json.JSONDecodeError:
                        return {"report": text}

        log.error("[ORCHESTRATOR] No usable output")
        raise AgentResponseError(message="Orchestrator returned no usable text/json part.")

    async def close(self):
        await self.client.aclose()
