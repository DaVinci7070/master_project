from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

class TemplateUploadRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=100)
    description: Optional[str] = None
    content: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list, max_length=20)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator('name')
    @classmethod
    def strip_whitespace_and_validate(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError('Name must contain at least 3 non-whitespace characters')
        return v

    @field_validator('tags', mode='after')
    @classmethod
    def validate_tags(cls, v: List[str]) -> List[str]:
        cleaned_tags = []
        for tag in v:
            tag = tag.strip()
            if len(tag) > 30:
                raise ValueError(f'Tag "{tag}" exceeds max length of 30')
            if tag:
                cleaned_tags.append(tag)
        return cleaned_tags

    @field_validator('content', 'metadata')
    @classmethod
    def validate_no_xss(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        import re
        xss_pattern = re.compile(
            r'<\s*(script|iframe|object|embed|applet)|javascript:|on[a-z]+\s*=',
            re.IGNORECASE
        )

        def check_value(val: Any):
            if isinstance(val, str):
                if xss_pattern.search(val):
                    raise ValueError('Potential XSS content detected')
            elif isinstance(val, dict):
                for k, sub_val in val.items():
                    check_value(k)
                    check_value(sub_val)
            elif isinstance(val, list):
                for item in val:
                    check_value(item)

        check_value(v)
        return v

class TemplateUploadResponse(BaseModel):
    user_collection: str
    upserted: int
    ids: List[str]

class TemplateDetail(BaseModel):
    id: str
    name: str
    description: Optional[str] = None


class TemplateResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    content: Dict[str, Any]
    tags: List[str]
    metadata: Dict[str, Any]
