
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class SummarizerInput(BaseModel):
    transcript: str = Field(..., description="Original transcript text")
    context_documents: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="RAG context documents"
    )
    template_result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Selected template for report structure"
    )

    defect_list: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Structured output from Defect Agent"
    )
    safety_report: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Structured output from Safety Agent"
    )
    claim_report: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Structured output from Claim Agent"
    )
    quality_report: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Structured output from Quality Agent"
    )

class SummarizerOutput(BaseModel):
    summary_report: str = Field(..., description="Generated structured report (JSON or Markdown)")
