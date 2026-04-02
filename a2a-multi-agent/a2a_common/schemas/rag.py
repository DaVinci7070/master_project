
from pydantic import BaseModel, Field
from typing import List, Dict, Any

class RAGInput(BaseModel):
    user_id: str = Field(..., description="User ID for scoped search")
    transcript: str = Field(..., description="Transcript for retrieval planning")

class RAGOutput(BaseModel):
    context_documents: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Retrieved context items"
    )
