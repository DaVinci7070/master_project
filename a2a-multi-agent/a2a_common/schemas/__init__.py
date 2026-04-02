
from .summarizer import SummarizerInput, SummarizerOutput
from .guard import GuardInput, GuardOutput
from .rag import RAGInput, RAGOutput
from .question import QuestionInput, QuestionOutput
from .template import TemplateInput, TemplateOutput
from .defect import DefectInput, DefectOutput
from .safety import SafetyInput, SafetyOutput
from .claim import ClaimInput, ClaimOutput
from .quality import QualityInput, QualityOutput

__all__ = [
    "SummarizerInput",
    "SummarizerOutput",
    "GuardInput",
    "GuardOutput",
    "RAGInput",
    "RAGOutput",
    "QuestionInput",
    "QuestionOutput",
    "TemplateInput",
    "TemplateOutput",
    "DefectInput",
    "DefectOutput",
    "SafetyInput",
    "SafetyOutput",
    "ClaimInput",
    "ClaimOutput",
    "QualityInput",
    "QualityOutput",
    "AGENT_SCHEMAS",
]

AGENT_SCHEMAS = {
    "agent_summarizer": (SummarizerInput, SummarizerOutput),
    "agent_guard": (GuardInput, GuardOutput),
    "agent_rag": (RAGInput, RAGOutput),
    "agent_question": (QuestionInput, QuestionOutput),
    "agent_template": (TemplateInput, TemplateOutput),
    "agent_defect": (DefectInput, DefectOutput),
    "agent_safety": (SafetyInput, SafetyOutput),
    "agent_claim": (ClaimInput, ClaimOutput),
    "agent_quality": (QualityInput, QualityOutput),
}
