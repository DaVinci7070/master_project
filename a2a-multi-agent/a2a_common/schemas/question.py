
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class QuestionInput(BaseModel):
    transcript: str = Field(..., description="Original transcript")
    template_result: Dict[str, Any] = Field(..., description="Template for validation")
    user_id: Optional[str] = Field(default=None, description="User ID for context")

class QuestionOutput(BaseModel):
    question_result: Dict[str, Any] = Field(
        ...,
        description="QS validation result with potential HITL questions"
    )
