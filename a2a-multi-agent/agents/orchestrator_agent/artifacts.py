
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field
from uuid import uuid4

class OrchestrationArtifact(BaseModel):

    key: str                              
    kind: Literal["text", "json", "list", "scalar", "unknown"] = "unknown"
    value: Any
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)  
    role: Optional[str] = None                     

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def touch(self) -> None:
        self.updated_at = datetime.utcnow()

class PlanStep(BaseModel):

    step_id: str = Field(default_factory=lambda: f"step_{uuid4().hex[:8]}")
    agent_id: str
    description: str

    input_mapping: Dict[str, str] = Field(default_factory=dict)
    output_mapping: Dict[str, str] = Field(default_factory=dict)

class StepStatus:
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"

class StepResult(BaseModel):

    step_id: str
    agent_id: str

    input_artifacts: Dict[str, str] = Field(default_factory=dict)   
    output_artifacts: Dict[str, str] = Field(default_factory=dict)  

    status: str = StepStatus.SUCCESS
    error_message: Optional[str] = None

    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None

    def mark_finished(self, status: str, error_message: Optional[str] = None) -> None:
        self.status = status
        self.error_message = error_message
        self.finished_at = datetime.utcnow()

class OrchestrationStatus:
    PENDING = "pending"
    WAITING_FOR_USER = "waiting_for_user"
    COMPLETED = "completed"
    FAILED = "failed"

class OrchestrationState(BaseModel):

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    goal: str

    artifacts: Dict[str, OrchestrationArtifact] = Field(default_factory=dict)
    history: List[StepResult] = Field(default_factory=list)
    status: str = OrchestrationStatus.PENDING
    plan: List[PlanStep] = Field(default_factory=list)
    current_step_idx: int = 0

    def has_artifact(self, key: str) -> bool:
        return key in self.artifacts

    def get_artifact(self, key: str) -> Optional[OrchestrationArtifact]:
        return self.artifacts.get(key)

    def get_value(self, key: str, default: Any = None) -> Any:
        art = self.artifacts.get(key)
        return art.value if art is not None else default

    def set_artifact(
        self,
        key: str,
        value: Any,
        *,
        kind: str = "unknown",
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        role: Optional[str] = None,
    ) -> OrchestrationArtifact:
        if key in self.artifacts:
            art = self.artifacts[key]
            art.value = value
            art.kind = kind or art.kind
            if description:
                art.description = description
            if tags:
                art.tags = list(set(art.tags + tags))
            if role:
                art.role = role
            art.touch()
        else:
            initial_tags = list(set([key] + (tags or [])))
            art = OrchestrationArtifact(
                key=key,
                value=value,
                kind=kind or "unknown",
                description=description,
                tags=initial_tags,
                role=role or key,
            )
            self.artifacts[key] = art
        return art

    def add_step_result(self, result: StepResult) -> None:
        self.history.append(result)