
from __future__ import annotations

from typing import List
from pydantic import BaseModel, Field


class QualityCheck(BaseModel):

    
    materials_used: List[str] = Field(
        default_factory=list,
        description="Verwendete Materialien mit Spezifikationen (z.B. 'Beton C25/30', 'Stahl S235')"
    )
    norms_mentioned: List[str] = Field(
        default_factory=list,
        description="Erwähnte Normen und Standards (z.B. 'DIN EN 206', 'DIN 1045')"
    )
    issues: List[str] = Field(
        default_factory=list,
        description="Identifizierte Qualitätsprobleme"
    )
    
    @property
    def total_materials(self) -> int:

        return len(self.materials_used)
    
    @property
    def total_norms(self) -> int:

        return len(self.norms_mentioned)
    
    @property
    def total_issues(self) -> int:

        return len(self.issues)


class QualityAnalysisResult(BaseModel):

    
    quality_check: QualityCheck = Field(default_factory=QualityCheck)
    summary: str = Field(
        default="",
        description="Kurze Zusammenfassung der Qualitätssituation"
    )
