
from pydantic import BaseModel, Field
from typing import List


class QualityInput(BaseModel):
  
    
    transcript: str = Field(
        ..., description="Transkript zur Qualitätsanalyse"
    )


class QualityResult(BaseModel):
 
    
    materials_used: List[str] = Field(
        default_factory=list,
        description="Liste der verwendeten Materialien mit Spezifikationen"
    )
    norms_mentioned: List[str] = Field(
        default_factory=list,
        description="Liste der erwähnten Normen und Standards"
    )
    issues: List[str] = Field(
        default_factory=list,
        description="Liste der identifizierten Qualitätsprobleme"
    )
    summary: str = Field(
        default="",
        description="Zusammenfassung der Qualitätssituation"
    )


class QualityOutput(BaseModel):
    
    
    quality_result: QualityResult = Field(
        ..., description="Das strukturierte Qualitätsergebnis"
    )
