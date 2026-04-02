
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict

class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., description="Tool name")
    description: Optional[str] = Field(default=None, description="Human readable description")
    inputSchema: Optional[Dict[str, Any]] = Field(default=None, description="JSON schema for input arguments")

class ToolCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)

class RagContextItem(BaseModel):
    id: Optional[str] = None
    title: Optional[str] = None
    score: Optional[float] = None
    source_tool: Optional[str] = None
    text: str = Field(..., description="Trimmed excerpt / content for downstream summarizer")

class RagContextMeta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tools_discovered: int = 0
    tools_used: List[str] = Field(default_factory=list)
    raw_items: int = 0
    returned_items: int = 0
    per_item_char_budget: int = 0
    total_char_budget: int = 0

class RagResultPayload(BaseModel):
    context_documents: List[RagContextItem] = Field(default_factory=list)