from __future__ import annotations

import json
import uuid as uuid_module
from typing import Any, Optional, Tuple, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from a2a.client import A2ACardResolver, A2AClient
from a2a.types import (
    MessageSendParams,
    SendMessageRequest,
    Message,
    Task,
    TextPart,
    DataPart,
    Part,
)

from a2a_common.retry import RetryPolicy, retry_with_backoff, is_retryable, DEFAULT_RETRY_POLICY
from a2a_common.envelope import create_error_envelope, MessageEnvelope
from a2a_common.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

class RemoteAgent:

    def __init__(
        self,
        base_url: str,
        timeout: float = 60.0,
        retry_policy: Optional[RetryPolicy] = None,
        agent_id: Optional[str] = None,  
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retry_policy = retry_policy or DEFAULT_RETRY_POLICY
        self.agent_id = agent_id or base_url
        self._correlation_id: Optional[str] = None

    def set_correlation_id(self, correlation_id: str) -> None:
        self._correlation_id = correlation_id

    def _generate_correlation_id(self) -> str:
        return self._correlation_id or uuid_module.uuid4().hex[:12]

    async def send_text(self, text: str) -> str:
        root = await self._send_message_raw(
            message_parts=[{"kind": "text", "text": text}]
        )
        return self._extract_text(root)

    async def send_json_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = json.dumps(payload, ensure_ascii=False)
        root = await self._send_message_raw(
            message_parts=[{"kind": "text", "text": text}]
        )
        response_text = self._extract_text(root)

        if not response_text:
            return {}

        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            return {"raw_output": response_text}

    async def call_structured(
        self,
        output_schema: Type[T],
        input_data: BaseModel,
        correlation_id: Optional[str] = None
    ) -> Tuple[T, Optional["AgentSignal"]]:
        from a2a_common.signals import AgentSignal
        from a2a_common.executor_utils import extract_output_data, extract_signal_from_parts
        if correlation_id:
            self.set_correlation_id(correlation_id)
        input_dict = input_data.model_dump()
        message_parts = [{"kind": "data", "data": input_dict}]
        logger.debug(
            "[A2A] Calling %s with input keys: %s",
            self.agent_id,
            list(input_dict.keys())
        )
        response_root = await self._send_message_raw(message_parts)
        result = getattr(response_root, "result", response_root)
        parts = []
        if isinstance(result, Message):
            parts = result.parts or []
        elif isinstance(result, Task) and result.artifacts:
            for artifact in result.artifacts:
                parts.extend(artifact.parts or [])
        signal = extract_signal_from_parts(parts)
        output_data = extract_output_data(parts)
        if output_data is None:
            logger.warning(
                "[A2A] No output data from %s, using empty dict",
                self.agent_id
            )
            output_data = {}
        try:
            validated_output = output_schema.model_validate(output_data)
        except ValidationError as e:
            logger.error(
                "[A2A] Output validation failed for %s: %s",
                self.agent_id,
                e
            )
            raise
        logger.debug(
            "[A2A] Received from %s: output=%s, signal=%s",
            self.agent_id,
            output_schema.__name__,
            signal.signal if signal else None
        )
        return validated_output, signal

    async def _send_message_raw(self, message_parts: list[dict[str, Any]]) -> Any:
        correlation_id = self._generate_correlation_id()

        @retry_with_backoff(
            policy=self.retry_policy,
            on_retry=lambda attempt, exc: logger.warning(
                "[%s] Retry %d for agent %s (correlation=%s): %s",
                "A2A",
                attempt + 1,
                self.agent_id,
                correlation_id,
                exc,
            ),
        )
        async def _do_send() -> Any:
            async with httpx.AsyncClient(timeout=self.timeout) as httpx_client:
                resolver = A2ACardResolver(
                    httpx_client=httpx_client,
                    base_url=self.base_url,
                )
                card = await resolver.get_agent_card()
                client = A2AClient(httpx_client=httpx_client, agent_card=card)

                payload: dict[str, Any] = {
                    "message": {
                        "role": "user",
                        "messageId": uuid_module.uuid4().hex,
                        "parts": message_parts,
                    }
                }

                request = SendMessageRequest(
                    id=str(uuid_module.uuid4()),
                    params=MessageSendParams(**payload),
                )

                logger.debug(
                    "[A2A] Sending to %s (correlation=%s)",
                    self.agent_id,
                    correlation_id,
                )

                response = await client.send_message(request)
                return response.root

        try:
            return await _do_send()
        except httpx.TimeoutException as e:
            logger.error(
                "[A2A] Timeout calling %s after %ds (correlation=%s): %s",
                self.agent_id,
                self.timeout,
                correlation_id,
                e,
            )
            raise AgentTimeoutError(
                agent_id=self.agent_id,
                timeout=self.timeout,
                correlation_id=correlation_id,
            ) from e
        except httpx.HTTPStatusError as e:
            logger.error(
                "[A2A] HTTP error from %s (correlation=%s): %s",
                self.agent_id,
                correlation_id,
                e,
            )
            raise AgentHTTPError(
                agent_id=self.agent_id,
                status_code=e.response.status_code,
                correlation_id=correlation_id,
            ) from e
        except Exception as e:
            logger.error(
                "[A2A] Error calling %s (correlation=%s): %s",
                self.agent_id,
                correlation_id,
                e,
            )
            raise AgentCommunicationError(
                agent_id=self.agent_id,
                message=str(e),
                correlation_id=correlation_id,
            ) from e

    def _extract_text(self, root: Any) -> str:
        result = getattr(root, "result", root)

        if isinstance(result, Message):
            return self._extract_from_message(result) or ""

        if isinstance(result, Task):
            return self._extract_from_task(result) or ""

        return ""

    def _extract_from_message(self, message: Message) -> Optional[str]:
        texts: list[str] = []
        for part in message.parts or []:
            if isinstance(part.root, TextPart):
                texts.append(part.root.text or "")
        return "\n".join(t for t in texts if t) or None

    def _extract_from_task(self, task: Task) -> Optional[str]:
        if not task.artifacts:
            return None
        collected: list[str] = []
        for artifact in task.artifacts:
            for part in artifact.parts or []:
                text = self._extract_from_part(part)
                if text:
                    collected.append(text)
        return "\n".join(collected) or None

    def _extract_from_part(self, part: Part) -> Optional[str]:
        root = part.root
        if isinstance(root, TextPart):
            return root.text or ""
        return None

class AgentCommunicationError(Exception):

    def __init__(
        self,
        agent_id: str,
        message: str,
        correlation_id: Optional[str] = None,
        retryable: bool = False,
    ):
        self.agent_id = agent_id
        self.correlation_id = correlation_id
        self.retryable = retryable
        super().__init__(f"Agent {agent_id} communication error: {message}")

class AgentTimeoutError(AgentCommunicationError):

    def __init__(
        self,
        agent_id: str,
        timeout: float,
        correlation_id: Optional[str] = None,
    ):
        self.timeout = timeout
        super().__init__(
            agent_id=agent_id,
            message=f"Timeout after {timeout}s",
            correlation_id=correlation_id,
            retryable=True,
        )

class AgentHTTPError(AgentCommunicationError):

    def __init__(
        self,
        agent_id: str,
        status_code: int,
        correlation_id: Optional[str] = None,
    ):
        self.status_code = status_code
        retryable = status_code in {408, 429, 500, 502, 503, 504}
        super().__init__(
            agent_id=agent_id,
            message=f"HTTP {status_code}",
            correlation_id=correlation_id,
            retryable=retryable,
        )