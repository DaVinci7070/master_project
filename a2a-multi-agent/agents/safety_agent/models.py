
from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class SafetyIncident(BaseModel):

    
    type: Literal["Accident", "Near Miss", "Hazard"] = Field(
        ...,
        description="Art des Vorfalls: Accident=Unfall, Near Miss=Beinahe-Unfall, Hazard=Gefahr"
    )
    description: str = Field(
        ...,
        description="Detaillierte Beschreibung des Vorfalls oder der Gefahr"
    )
    severity: Literal["Low", "Medium", "High", "Critical"] = Field(
        ...,
        description="Schweregrad: Low=gering, Medium=mittel, High=hoch, Critical=lebensgefährlich"
    )
    location: Optional[str] = Field(
        default=None,
        description="Ortsangabe des Vorfalls (z.B. 'Gerüst OG 2', 'Baugrube Nord')"
    )
    people_involved: Optional[str] = Field(
        default=None,
        description="Beteiligte Personen (Namen oder Funktionen)"
    )
    psa_related: bool = Field(
        default=False,
        description="Bezieht sich der Vorfall auf PSA (Persönliche Schutzausrüstung)?"
    )


class SafetyReport(BaseModel):

    
    incidents: List[SafetyIncident] = Field(
        default_factory=list,
        description="Liste aller identifizierten Sicherheitsvorfälle"
    )
    compliance_status: Literal[
        "compliant", 
        "minor_violations", 
        "major_violations", 
        "critical_violations"
    ] = Field(
        default="compliant",
        description="Gesamtstatus der Sicherheits-Compliance"
    )
    
    @property
    def incident_count(self) -> int:

        return len(self.incidents)
    
    @property
    def critical_count(self) -> int:

        return sum(1 for i in self.incidents if i.severity == "Critical")
    
    @property
    def high_count(self) -> int:

        return sum(1 for i in self.incidents if i.severity == "High")
    
    @property
    def accident_count(self) -> int:

        return sum(1 for i in self.incidents if i.type == "Accident")


class SafetyAnalysisResult(BaseModel):

    
    report: SafetyReport = Field(default_factory=SafetyReport)
    summary: str = Field(
        default="",
        description="Kurze Zusammenfassung der Sicherheitslage"
    )
