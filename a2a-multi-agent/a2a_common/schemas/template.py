
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class TemplateInput(BaseModel):
    transcript: str = Field(..., description="Transcript for template selection")
    user_id: str = Field(..., description="User ID for template scope")
    template_id: Optional[str] = Field(
        default=None,
        description="Optional specific template ID"
    )

class TemplateOutput(BaseModel):
    template_result: Dict[str, Any] = Field(
        ...,
        description="Selected template as TemplateResult"
    )
