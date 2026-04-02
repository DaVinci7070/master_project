
from __future__ import annotations

from enum import Enum
from typing import Optional, Dict, Any

from pydantic import BaseModel, Field

class SignalType(str, Enum):
    CONTINUE = "CONTINUE"
    SUSPEND = "SUSPEND"
    ERROR = "ERROR"
    SUCCESS = "SUCCESS"

class AgentSignal(BaseModel):
    signal: SignalType = Field(..., description="Signal type")
    reason: Optional[str] = Field(None, description="Human-readable reason")
    data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional data (e.g., questions for HITL)"
    )

    class Config:
        use_enum_values = True

def create_continue_signal() -> AgentSignal:
    return AgentSignal(signal=SignalType.CONTINUE)

def create_suspend_signal(
    data: Dict[str, Any],
    reason: str = "MISSING_INFORMATION"
) -> AgentSignal:
    return AgentSignal(
        signal=SignalType.SUSPEND,
        reason=reason,
        data=data
    )

def create_error_signal(
    reason: str,
    error_details: Optional[Dict[str, Any]] = None
) -> AgentSignal:
    return AgentSignal(
        signal=SignalType.ERROR,
        reason=reason,
        data=error_details or {}
    )

def create_success_signal(data: Optional[Dict[str, Any]] = None) -> AgentSignal:
    return AgentSignal(
        signal=SignalType.SUCCESS,
        data=data or {}
    )
