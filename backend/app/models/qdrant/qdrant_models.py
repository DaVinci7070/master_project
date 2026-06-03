from pydantic import BaseModel, Field
from typing import Any, List, Optional, Union, Dict
from dataclasses import dataclass, field

from pydantic.v1 import UUID4

FieldValue = Union[str, int, float, bool, None]

@dataclass(frozen=True)
class ReportRecord:
    user_id: str
    report_id: Optional[str]
    title: Optional[str]
    text: str
    fields: Dict[str, FieldValue]
    created_at: Optional[str]
    created_at_ts: Optional[float]
    tags: list[str]
    source: Optional[str]
    metadata: dict[str, Any]
    original_transcript: Optional[str] = None
    location: Optional[str] = None
    time: Optional[str] = None

@dataclass(frozen=True)
class UpsertBatchResult:
    user_collection: str
    upserted: int
    ids: list[str]

@dataclass(frozen=True)
class SearchHit:
    id: str
    score: float
    report_id: Optional[str]
    title: Optional[str]
    text: Optional[str]
    fields: Optional[Dict[str, FieldValue]]
    created_at: Optional[str]
    created_at_ts: Optional[float]
    tags: list[str]
    source: Optional[str]
    snippet: Optional[str]
    metadata: dict[str, Any]
    original_transcript: Optional[str] = None
    location: Optional[str] = None
    time: Optional[str] = None

@dataclass(frozen=True)
class QdrantPointPayload:
    report_id: str
    user_id: str
    title: str
    text: str
    fields: Dict[str, FieldValue]
    created_at: str
    created_at_ts: float
    tags: list[str]
    source: str
    metadata: dict[str, Any]
    original_transcript: Optional[str] = None
    location: Optional[str] = None
    time: Optional[str] = None

@dataclass(frozen=True)
class QdrantPoint:
    id: str
    vector: list[float]
    payload: QdrantPointPayload

@dataclass(frozen=True)
class TemplateRecord:
    user_id: str
    template_id: UUID4
    name: str
    description: Optional[str]
    content: Dict[str, Any]
    tags: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class TemplateHit:
    id: str         
    score: float
    template_id: UUID4
    name: Optional[str]
    description: Optional[str]
    content: Optional[Dict[str, Any]]  
    tags: List[str]
    snippet: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class QdrantTemplatePayload:
    user_id: str
    template_id: UUID4
    name: str
    description: Optional[str]
    content: Dict[str, Any]
    tags: List[str]
    created_at: str
    metadata: Dict[str, Any]
