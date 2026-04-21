from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "DecisionGate",
    "MicroFormField",
    "OutlineArtifact",
    "OutlineRubric",
    "ParticipantFAQEntry",
    "RiskEntry",
]


class MicroFormField(BaseModel):
    key: str
    label: str
    field_type: str = "text"
    required: bool = True
    options: list[str] = Field(default_factory=list)


class ParticipantFAQEntry(BaseModel):
    key: str
    question: str
    answer: str
    tags: list[str] = Field(default_factory=list)


class OutlineRubric(BaseModel):
    coverage_dimensions: list[str] = Field(default_factory=list)
    risk_checks: list[str] = Field(default_factory=list)
    mandatory_close_axes: list[str] = Field(default_factory=list)


class RiskEntry(BaseModel):
    risk: str
    mitigation: str


class DecisionGate(BaseModel):
    gate: str
    rationale: str


class OutlineArtifact(BaseModel):
    research_question: str = ""
    sampling_frame: str = ""
    exclusion_criteria: str = ""
    publication_intent: str = ""
    axes: list[str] = Field(default_factory=list)
    objectives: list[str] = Field(default_factory=list)
    probes: list[str] = Field(default_factory=list)
    risk_register: list[RiskEntry] = Field(default_factory=list)
    grounding_sources_approved: list[str] = Field(default_factory=list)
    readiness_rationale: str = ""
    decision_gate: DecisionGate | None = None
    suggested_search_queries: list[str] = Field(default_factory=list)
    min_n: int = 6
    max_n: int = 40
    rubric: OutlineRubric = Field(default_factory=OutlineRubric)
    freshness_query: str = ""
    persona_hints: dict[str, str] = Field(default_factory=dict)
    consent_language: str = ""
    micro_form_schema: list[MicroFormField] = Field(default_factory=list)
    scientist_summary: str = ""
    study_context: str = ""
    market_context: str = ""
    technical_context: str = ""
    aggregate_graph_context: str = ""
    participant_faq: list[ParticipantFAQEntry] = Field(default_factory=list)
