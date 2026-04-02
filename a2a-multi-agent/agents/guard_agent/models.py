
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class HallucinationIssue(BaseModel):
    field: str = "report"            
    span: str                        
    reason: str                      
    correction: Optional[str] = None 

class GuardResult(BaseModel):
    has_hallucinations: bool = False
    corrected_report: str
    issues: List[HallucinationIssue] = Field(default_factory=list)

class GuardInputs(BaseModel):
    transcript: str
    report: str
    context_documents: Optional[List[Dict[str, Any]]] = None

class GuardTask(BaseModel):
    type: str = "task"
    step_id: str
    agent_id: str
    description: str
    goal: str
    inputs: GuardInputs