
from __future__ import annotations

import uuid
from typing import Type, TypeVar, Optional, List, Any

from pydantic import BaseModel, ValidationError
from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue
from a2a.types import Message, DataPart, TextPart, Part

from a2a_common.signals import AgentSignal
from a2a_common.utils import safe_json_parse
from a2a_common.logging import get_logger

logger = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)

SIGNAL_KEY = "_signal"

def extract_input_model(
    context: RequestContext,
    input_schema: Type[T]
) -> T:
    if not context.message or not context.message.parts:
        raise ValueError(f"No message parts found for {input_schema.__name__}")
    combined_data: dict = {}
    for part in context.message.parts:
        root = part.root if hasattr(part, 'root') else part
        if isinstance(root, DataPart) and root.data:
            if isinstance(root.data, dict):
                if SIGNAL_KEY not in root.data:
                    combined_data.update(root.data)
                if "_slot" in root.data and "value" in root.data:
                    slot_name = root.data["_slot"]
                    combined_data[slot_name] = root.data["value"]
        elif isinstance(root, TextPart) and root.text:
            parsed = safe_json_parse(root.text)
            if isinstance(parsed, dict) and SIGNAL_KEY not in parsed:
                combined_data.update(parsed)
    if not combined_data:
        raise ValueError(
            f"No valid input data for {input_schema.__name__} found in context"
        )
    try:
        return input_schema.model_validate(combined_data)
    except ValidationError as e:
        logger.error(f"Validation failed for {input_schema.__name__}: {e}")
        raise

async def send_output_model(
    event_queue: EventQueue,
    output_model: BaseModel,
    signal: Optional[AgentSignal] = None
) -> None:
    parts: List[Part] = []
    output_data = output_model.model_dump()
    parts.append(Part(root=DataPart(data=output_data)))
    if signal:
        signal_part = {SIGNAL_KEY: signal.model_dump()}
        parts.append(Part(root=DataPart(data=signal_part)))
    msg = Message(
        messageId=str(uuid.uuid4()),
        role="agent",
        parts=parts
    )
    await event_queue.enqueue_event(msg)
    logger.debug(
        "Sent %s%s",
        output_model.__class__.__name__,
        f" with {signal.signal} signal" if signal else ""
    )

def extract_output_data(parts: List[Any]) -> Optional[dict]:
    for part in parts:
        root = getattr(part, "root", part)
        if isinstance(root, DataPart) and isinstance(root.data, dict):
            if SIGNAL_KEY not in root.data:
                return root.data
        if isinstance(root, TextPart) and root.text:
            parsed = safe_json_parse(root.text)
            if isinstance(parsed, dict) and SIGNAL_KEY not in parsed:
                return parsed
    return None

def extract_signal_from_parts(parts: List[Any]) -> Optional[AgentSignal]:
    for part in parts:
        root = getattr(part, "root", part)
        if isinstance(root, DataPart) and isinstance(root.data, dict):
            if SIGNAL_KEY in root.data:
                try:
                    return AgentSignal.model_validate(root.data[SIGNAL_KEY])
                except ValidationError as e:
                    logger.warning(f"Invalid signal in DataPart: {e}")
        if isinstance(root, TextPart) and root.text:
            parsed = safe_json_parse(root.text)
            if isinstance(parsed, dict) and SIGNAL_KEY in parsed:
                try:
                    return AgentSignal.model_validate(parsed[SIGNAL_KEY])
                except ValidationError:
                    pass
    return None
