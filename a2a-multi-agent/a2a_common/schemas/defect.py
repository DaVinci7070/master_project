
from pydantic import BaseModel, Field
from typing import List, Literal, Any


class DefectEntrySchema(BaseModel):

    
    location: str = Field(..., description="Ortsangabe des Mangels")
    description: str = Field(..., description="Beschreibung des Mangels")
    severity: Literal["Low", "Medium", "High", "Critical"] = Field(
        ..., description="Schweregrad"
    )
    action_required: bool = Field(..., description="Handlungsbedarf")


class DefectInput(BaseModel):

    
    transcript: str = Field(
        ..., description="Transkript zur Mängelanalyse"
    )


class DefectResult(BaseModel):

    
    defects: List[Any] = Field(
        default_factory=list,
        description="Liste der extrahierten Mängel"
    )
    total_count: int = Field(
        default=0,
        description="Gesamtzahl der Mängel"
    )
    critical_count: int = Field(
        default=0,
        description="Anzahl kritischer Mängel"
    )
    summary: str = Field(
        default="",
        description="Zusammenfassung der Mängelsituation"
    )


class DefectOutput(BaseModel):

    
    defect_result: DefectResult = Field(
        ..., description="Das strukturierte Mängelergebnis"
    )
