import uuid
from sqlalchemy import Column, String, Text, JSON, Boolean, DateTime, func

from app.models.sql.base import Base


class ArtifactSchema(Base):
    """
    Database model for artifact type schemas.

    Enables runtime schema validation from database definitions
    instead of hardcoded Pydantic models.
    """
    __tablename__ = "artifact_schemas"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    artifact_type = Column(String(100), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    json_schema = Column(JSON, nullable=False)

    example_payload = Column(JSON, nullable=True)

    version = Column(String(50), default="1.0.0")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    producing_agents = Column(JSON, default=list)
    consuming_agents = Column(JSON, default=list)
