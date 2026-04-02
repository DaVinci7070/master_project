
from __future__ import annotations
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field

class QuestionInputs(BaseModel):
    transcript: str = Field(..., description="The original transcript to analyze.")
    template_result: Optional[Dict[str, Any]] = Field(None, description="The selected template to check against.")
    user_id: Optional[str] = Field(None, description="Optional user ID for context.")

class ClarificationQuestion(BaseModel):
    id: str = Field(..., description="Unique ID for the question.")
    question: str = Field(..., description="The question text to show the user.")
    field_name: Optional[str] = Field(None, description="The name of the field this question refers to.")
    kind: Literal["text", "single_choice", "multi_choice"] = "text"
    options: Optional[List[str]] = None
    required: bool = True
    confidence: Optional[float] = None

class QuestionResult(BaseModel):
    has_questions: bool = Field(False, description="Whether the agent found missing info and has questions.")
    questions: List[ClarificationQuestion] = Field(default_factory=list)
    initial_report_draft: Optional[str] = Field(None, description="An optional draft if only minor info is missing.")

class QuestionTask(BaseModel):
    step_id: str
    agent_id: str
    goal: str
    inputs: QuestionInputs
