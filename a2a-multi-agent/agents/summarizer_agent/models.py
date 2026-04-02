
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class SummarizerInputs(BaseModel):
    transcript: str
    context_documents: Optional[List[Dict[str, Any]]] = None
    template_result: Optional[Dict[str, Any]] = None

class SummarizerTask(BaseModel):
    type: str = "task"
    step_id: str
    agent_id: str
    description: str
    goal: str
    inputs: SummarizerInputs

class SummarizerResult(BaseModel):
    summary_report: str