
from __future__ import annotations

from typing import List, Literal
from pydantic import BaseModel, Field


class DefectEntry(BaseModel):

    
    location: str = Field(
        ...,
        description="Präzise Ortsangabe des Mangels (z.B. 'EG, Flur', 'OG 1, Bad', 'Keller, Technikraum')"
    )
    description: str = Field(
        ...,
        description="Detaillierte Beschreibung des Mangels"
    )
    severity: Literal["Low", "Medium", "High", "Critical"] = Field(
        ...,
        description="Schweregrad: Low=kosmetisch, Medium=vor Abnahme, High=sofort, Critical=Sicherheit"
    )
    action_required: bool = Field(
        ...,
        description="Ob sofortiger Handlungsbedarf besteht"
    )


class DefectList(BaseModel):

    
    items: List[DefectEntry] = Field(
        default_factory=list,
        description="Liste der gefundenen Mängel"
    )
    
    @property
    def total_count(self) -> int:

        return len(self.items)
    
    @property
    def critical_count(self) -> int:

        return sum(1 for item in self.items if item.severity == "Critical")
    
    @property
    def high_count(self) -> int:

        return sum(1 for item in self.items if item.severity == "High")


class DefectAnalysisResult(BaseModel):

    
    defects: DefectList = Field(default_factory=DefectList)
    summary: str = Field(
        default="",
        description="Kurze Zusammenfassung der Mängelsituation"
    )
