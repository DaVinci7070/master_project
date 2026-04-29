import uuid
from sqlalchemy import (
    Column, Integer, String, Boolean, JSON, DateTime, func, Text
)

from app.models.sql.base import Base
from app.models.sql.versioned_models import Prompt, Agent, Skill
from app.models.sql.evaluation_models import BenchmarkRun, BenchmarkTaskResult  # noqa: F401

__all__ = ["Base", "Report", "Prompt", "Agent", "Skill", "BenchmarkRun", "BenchmarkTaskResult"]

class Report(Base):
    __tablename__ = "reports"

    id = Column(String(36), primary_key=True, index=True, default=lambda: str(uuid.uuid4()))

    hashed_user_id = Column(String(64), index=True, nullable=False)

    status = Column(String, default="pending_review", index=True, nullable=False)
    is_editable = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    original_transcript = Column(Text, nullable=True)
    location = Column(String(255), nullable=True)
    event_time = Column(String(255), nullable=True)

    title = Column(String(255), nullable=True)
    report_content = Column(Text, nullable=False)  
    report_format = Column(String(16), nullable=False, default="text", index=True)
    fields = Column(JSON, nullable=False, default=dict)  
    tags = Column(JSON, nullable=False, default=list)    
    report_metadata = Column(JSON, nullable=False, default=dict)  
