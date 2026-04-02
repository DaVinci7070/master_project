
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

class EnvelopeMetadata(BaseModel):

    message_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    correlation_id: Optional[str] = Field(
        default=None,
        description="Optional correlation ID for request-response tracking",
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_agent: str = Field(..., description="Sending agent ID")
    target_agent: str = Field(..., description="Receiving agent ID")
    version: str = Field(default="1.0", description="Envelope protocol version")

class EnvelopeError(BaseModel):

    error_code: str = Field(..., description="Error code (e.g., TIMEOUT, PARSE_ERROR)")
    error_message: str = Field(..., description="Human-readable error message")
    retryable: bool = Field(default=False, description="Whether the error is retryable")
    details: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional error context"
    )

class MessageEnvelope(BaseModel, Generic[T]):

    metadata: EnvelopeMetadata
    payload: Optional[T] = Field(
        default=None, description="The actual agent-specific message content"
    )
    error: Optional[EnvelopeError] = Field(
        default=None, description="Error information if message failed"
    )

def wrap_payload(
    payload: T,
    source: str,
    target: str,
    correlation_id: Optional[str] = None,
) -> MessageEnvelope[T]:
    metadata = EnvelopeMetadata(
        source_agent=source,
        target_agent=target,
        correlation_id=correlation_id,
    )
    return MessageEnvelope(metadata=metadata, payload=payload)

def unwrap_payload(envelope: MessageEnvelope[T]) -> T:
    if envelope.error:
        raise ValueError(
            f"[{envelope.error.error_code}] {envelope.error.error_message}"
        )

    if envelope.payload is None:
        raise ValueError("Envelope has no payload")

    return envelope.payload

def create_error_envelope(
    source: str,
    target: str,
    error_code: str,
    message: str,
    retryable: bool = False,
    correlation_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> MessageEnvelope[None]:
    metadata = EnvelopeMetadata(
        source_agent=source,
        target_agent=target,
        correlation_id=correlation_id,
    )
    error = EnvelopeError(
        error_code=error_code,
        error_message=message,
        retryable=retryable,
        details=details,
    )
    return MessageEnvelope(metadata=metadata, payload=None, error=error)
