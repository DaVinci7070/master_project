from uuid import UUID
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field, field_validator, UUID4
from app.models.qdrant.qdrant_models import FieldValue

class SubmitAnswersRequest(BaseModel):
    run_id: UUID4
    answers: Dict[str, Any] = Field(default_factory=dict) 
    answer_transcript: Optional[str] = None

    @field_validator('answers')
    @classmethod
    def validate_answers_xss(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        import re
        xss_pattern = re.compile(
            r'<\s*(script|iframe|object|embed|applet)|javascript:|on[a-z]+\s*=',
            re.IGNORECASE
        )
        def check_value(val: Any):
            if isinstance(val, str):
                if xss_pattern.search(val):
                    raise ValueError('Potential XSS content detected in answers')
            elif isinstance(val, dict):
                for k, sub_val in val.items():
                    check_value(k)
                    check_value(sub_val)
            elif isinstance(val, list):
                for item in val:
                    check_value(item)
        check_value(v)
        return v

    @field_validator('answer_transcript')
    @classmethod
    def validate_answer_transcript_xss(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        import re
        xss_pattern = re.compile(
            r'<\s*(script|iframe|object|embed|applet)|javascript:|on[a-z]+\s*=',
            re.IGNORECASE
        )
        if xss_pattern.search(v):
            raise ValueError('Potential XSS content detected in answer_transcript')
        return v

class AskTranscriptQuestionRequest(BaseModel):
    transcript: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    report_id: Optional[UUID4] = None

    @field_validator('transcript', 'question')
    @classmethod
    def validate_no_xss(cls, v: str) -> str:
        import re
        xss_pattern = re.compile(
            r'<\s*(script|iframe|object|embed|applet)|javascript:|on[a-z]+\s*=',
            re.IGNORECASE
        )
        if xss_pattern.search(v):
            raise ValueError('Potential XSS content detected')
        return v

class AskTranscriptQuestionResponse(BaseModel):
    user_id: str
    answer: str
    report_id: Optional[str] = None

class GenerateReportRequest(BaseModel):
    transcript: str = Field(..., min_length=50) 
    template_id: Optional[UUID4] = None
    run_id: Optional[UUID4] = None
    answers: Optional[Dict[str, Any]] = None

    @field_validator('transcript')
    @classmethod
    def validate_no_xss_transcript(cls, v: str) -> str:
        import re
        xss_pattern = re.compile(
            r'<\s*(script|iframe|object|embed|applet)|javascript:|on[a-z]+\s*=',
            re.IGNORECASE
        )
        if xss_pattern.search(v):
            raise ValueError('Potential XSS content detected')
        return v

    @field_validator('answers')
    @classmethod
    def validate_answers_xss(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if v is None:
            return v
        import re
        xss_pattern = re.compile(
            r'<\s*(script|iframe|object|embed|applet)|javascript:|on[a-z]+\s*=',
            re.IGNORECASE
        )
        def check_value(val: Any):
            if isinstance(val, str):
                if xss_pattern.search(val):
                    raise ValueError('Potential XSS content detected in answers')
            elif isinstance(val, dict):
                for k, sub_val in val.items():
                    check_value(k)
                    check_value(sub_val)
            elif isinstance(val, list):
                for item in val:
                    check_value(item)
        check_value(v)
        return v

class PreProcessTranscriptRequest(BaseModel):
    template_id: Optional[str] = None
    transcript: str

class ClarificationQuestion(BaseModel):
    id: str
    question: str
    field_name: Optional[str] = None
    kind: Literal["text", "single_choice", "multi_choice"] = "text"
    options: Optional[List[str]] = None
    required: bool = True
    confidence: Optional[float] = None

class GenerateReportResponse(BaseModel):
    report_id: Optional[str] = None
    status: str
    report_content: Optional[str] = None
    report_format: Optional[Literal["json", "text"]] = None
    run_id: Optional[str] = None
    questions: List[ClarificationQuestion] = Field(default_factory=list)
    title: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    report_type: Optional[str] = None
    original_transcript: Optional[str] = None
    location: Optional[str] = None
    time: Optional[str] = None

class ReportResponse(BaseModel):
    report_id: str
    user_id: str
    summary: str
    status: str
    tags: List[str]
    title: str
    original_transcript: Optional[str] = None
    location: Optional[str] = None
    time: Optional[str] = None

class PaginatedReportResponse(BaseModel):
    items: List[ReportResponse]
    total: int
    skip: int
    limit: int

class QuestionsToTranscriptResponse(BaseModel):
    questions: List[str]

class ReportIn(BaseModel):
    report_id: str
    title: Optional[str] = None
    text: str = Field(min_length=1)
    fields: Dict[str, FieldValue] = Field(default_factory=dict)
    created_at: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    source: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    original_transcript: Optional[str] = None
    location: Optional[str] = None
    time: Optional[str] = None

class BatchUploadRequest(BaseModel):
    reports: List[ReportIn] = Field(..., min_items=1)

class BatchUploadResponse(BaseModel):
    user_collection: str
    upserted: int
    ids: List[str]

class TranscriptIntakeRequest(BaseModel):
    transcript: str

class TranscriptIntakeResponse(BaseModel):
    intake_id: str
    status: Literal["pending_user", "ready"]
    questions: List[ClarificationQuestion]