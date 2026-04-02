
from pydantic import BaseModel, Field
from typing import List, Literal, Optional, Any


class SafetyIncidentSchema(BaseModel):

    
    type: Literal["Accident", "Near Miss", "Hazard"] = Field(
        ..., description="Art des Vorfalls"
    )
    description: str = Field(..., description="Beschreibung des Vorfalls")
    severity: Literal["Low", "Medium", "High", "Critical"] = Field(
        ..., description="Schweregrad"
    )
    location: Optional[str] = Field(None, description="Ortsangabe")
    people_involved: Optional[str] = Field(None, description="Beteiligte Personen")
    psa_related: bool = Field(False, description="PSA-bezogen")


class SafetyInput(BaseModel):

    
    transcript: str = Field(
        ..., description="Transkript zur Sicherheitsanalyse"
    )


class SafetyResult(BaseModel):

    
    incidents: List[Any] = Field(
        default_factory=list,
        description="Liste der identifizierten Sicherheitsvorfälle"
    )
    incident_count: int = Field(
        default=0,
        description="Gesamtzahl der Vorfälle"
    )
    critical_count: int = Field(
        default=0,
        description="Anzahl kritischer Vorfälle"
    )
    accident_count: int = Field(
        default=0,
        description="Anzahl der Unfälle"
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
    summary: str = Field(
        default="",
        description="Zusammenfassung der Sicherheitslage"
    )


class SafetyOutput(BaseModel):

    
    safety_result: SafetyResult = Field(
        ..., description="Das strukturierte Sicherheitsergebnis"
    )
