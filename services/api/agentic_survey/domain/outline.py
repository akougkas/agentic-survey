from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

__all__ = [
    "DecisionGate",
    "MicroFormField",
    "OutlineArtifact",
    "OutlineRubric",
    "ParticipantFAQEntry",
    "RiskEntry",
    "SurveyQuestion",
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


class SurveyQuestion(BaseModel):
    id: str
    tier: str = ""
    kind: str = "open"
    prompt: str
    options: list[str] = Field(default_factory=list)
    applies_to_roles: list[str] = Field(default_factory=list)
    axis_tag: str = ""
    notes: str = ""
    follow_up_hints: list[str] = Field(default_factory=list)
    saturation_signals: list[str] = Field(default_factory=list)
    leading_language_avoid: list[str] = Field(default_factory=list)

    @field_validator("id", "prompt")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must be non-empty")
        return stripped

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        if value not in {"open", "select_one", "select_many", "likert_5", "rank"}:
            raise ValueError("kind must be one of open, select_one, select_many, likert_5, rank")
        return value

    @model_validator(mode="after")
    def validate_options_for_kind(self) -> "SurveyQuestion":
        if self.kind in {"select_one", "select_many", "rank"} and not self.options:
            raise ValueError(f"kind='{self.kind}' requires at least one option")
        return self


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
    question_bank: list[SurveyQuestion] = Field(default_factory=list)
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
