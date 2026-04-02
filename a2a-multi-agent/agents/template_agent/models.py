
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

class TemplateInputs(BaseModel):
    transcript: str
    user_id: str
    template_id: Optional[str] = None

class TemplateTask(BaseModel):
    type: str = "task"
    step_id: str
    agent_id: str
    description: str
    goal: str
    inputs: TemplateInputs

class TemplateResult(BaseModel):
    template_id: Optional[str] = None
    template_name: Optional[str] = None
    template: Dict[str, Any] = Field(default_factory=dict)
    score: Optional[float] = None