
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional, List

class GuardInput(BaseModel):
    transcript: str = Field(..., description="Original transcript (source of truth)")
    report: str = Field(..., description="Report to validate for hallucinations")
    context_documents: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="RAG context documents (treated as valid source alongside transcript)"
    )

class GuardOutput(BaseModel):
    corrected_report: str = Field(..., description="Corrected/validated report")
    corrections_made: Optional[List[str]] = Field(
        default=None,
        description="List of corrections applied"
    )
