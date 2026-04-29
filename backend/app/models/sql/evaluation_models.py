"""SQLAlchemy models for persistent benchmark evaluation results."""
import uuid

from sqlalchemy import Column, String, Integer, Float, Boolean, Text, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship

from app.models.sql.base import Base


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    suite = Column(String, nullable=False)
    ablation_mode = Column(String, nullable=True)
    seed = Column(Integer, nullable=True)
    status = Column(String, default="running")  # running / completed / failed
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Aggregierte Metriken
    tasks_total = Column(Integer, default=0)
    tasks_passed = Column(Integer, default=0)
    pass_at_1 = Column(Float, default=0.0)
    total_tokens = Column(Integer, default=0)
    total_tokens_input = Column(Integer, default=0)
    total_tokens_output = Column(Integer, default=0)
    total_duration_ms = Column(Integer, default=0)
    avg_score = Column(Float, default=0.0)

    # Relationship
    task_results = relationship("BenchmarkTaskResult", back_populates="run", cascade="all, delete-orphan")


class BenchmarkTaskResult(Base):
    __tablename__ = "benchmark_task_results"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(String, ForeignKey("benchmark_runs.id"), nullable=False)
    task_id = Column(String, nullable=False)
    level = Column(String, nullable=True)
    status = Column(String, nullable=True)  # resolved / failed / timeout / error
    passed = Column(Boolean, default=False)
    score = Column(Float, default=0.0)

    # Metriken
    duration_ms = Column(Integer, default=0)
    agents_executed = Column(Integer, default=0)
    tokens_total = Column(Integer, default=0)
    tokens_input = Column(Integer, default=0)
    tokens_output = Column(Integer, default=0)

    # Debug-Info
    missing_keywords = Column(JSON, default=list)
    missing_sections = Column(JSON, default=list)
    error = Column(Text, nullable=True)

    # Challenge-Referenz
    challenge_id = Column(String, nullable=True)

    # Relationship
    run = relationship("BenchmarkRun", back_populates="task_results")
