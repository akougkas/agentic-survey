from __future__ import annotations

from pydantic import BaseModel, Field

from agentic_survey.repository import (
    MicroFormField,
    OutlineArtifact,
    OutlineRubric,
    ParticipantFAQEntry,
)

__all__ = [
    "DecisionGate",
    "OutlineArtifactV2",
    "RiskEntry",
    "from_v1",
    "to_v1",
]


class RiskEntry(BaseModel):
    risk: str
    mitigation: str


class DecisionGate(BaseModel):
    gate: str
    rationale: str


class OutlineArtifactV2(BaseModel):
    """Designer outline (M3 v2 shape).

    v2 adds the five-axis fields (research_question, sampling_frame,
    exclusion_criteria, publication_intent, risk_register) plus the closure
    surface (readiness_rationale, decision_gate, grounding_sources_approved,
    suggested_search_queries). Legacy v1 fields are preserved verbatim so
    ``from_v1`` -> ``to_v1`` round-trips without loss while new Designer code
    reads and writes the v2 surface.
    """

    # --- Axes 1-5 primary fields ---
    research_question: str = ""
    sampling_frame: str = ""
    exclusion_criteria: str = ""
    publication_intent: str = ""
    axes: list[str] = Field(default_factory=list)
    probes: list[str] = Field(default_factory=list)
    risk_register: list[RiskEntry] = Field(default_factory=list)
    grounding_sources_approved: list[str] = Field(default_factory=list)
    readiness_rationale: str = ""
    decision_gate: DecisionGate | None = None
    suggested_search_queries: list[str] = Field(default_factory=list)
    min_n: int = 6
    max_n: int = 40

    # --- legacy v1 fields preserved (additive compatibility) ---
    objectives: list[str] = Field(default_factory=list)
    rubric: OutlineRubric | None = None
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


def from_v1(outline: OutlineArtifact) -> OutlineArtifactV2:
    """Lift a legacy OutlineArtifact to the v2 shape without loss.

    Legacy fields migrate verbatim. ``freshness_query`` is copied into
    ``suggested_search_queries`` (and kept on the legacy slot) so new code
    reading v2 sees the design-time search affordances immediately. The v2
    axis fields default to empty; A5 readiness validation handles the
    hard-floor minimums when the Designer starts populating them.
    """
    suggested = [outline.freshness_query] if outline.freshness_query else []
    return OutlineArtifactV2(
        probes=list(outline.probes),
        suggested_search_queries=suggested,
        min_n=outline.min_n,
        max_n=outline.max_n,
        objectives=list(outline.objectives),
        rubric=outline.rubric,
        freshness_query=outline.freshness_query,
        persona_hints=dict(outline.persona_hints),
        consent_language=outline.consent_language,
        micro_form_schema=[field.model_copy(deep=True) for field in outline.micro_form_schema],
        scientist_summary=outline.scientist_summary,
        study_context=outline.study_context,
        market_context=outline.market_context,
        technical_context=outline.technical_context,
        aggregate_graph_context=outline.aggregate_graph_context,
        participant_faq=[entry.model_copy(deep=True) for entry in outline.participant_faq],
    )


def to_v1(v2: OutlineArtifactV2) -> OutlineArtifact:
    """Project a v2 outline back onto the legacy shape for existing writers.

    Prefers legacy-slot values when both v2 and legacy carry a field (legacy
    slot is the canonical v1 storage); falls back to v2 primaries otherwise.
    ``freshness_query`` resolves to the legacy slot, then the first element
    of ``suggested_search_queries``, then the empty string.
    """
    rubric = v2.rubric if v2.rubric is not None else OutlineRubric()
    freshness_query = v2.freshness_query
    if not freshness_query and v2.suggested_search_queries:
        freshness_query = v2.suggested_search_queries[0]
    probes = list(v2.probes) if v2.probes else []
    return OutlineArtifact(
        objectives=list(v2.objectives),
        probes=probes,
        rubric=rubric,
        min_n=v2.min_n,
        max_n=v2.max_n,
        freshness_query=freshness_query,
        persona_hints=dict(v2.persona_hints),
        consent_language=v2.consent_language,
        micro_form_schema=[field.model_copy(deep=True) for field in v2.micro_form_schema],
        scientist_summary=v2.scientist_summary,
        study_context=v2.study_context,
        market_context=v2.market_context,
        technical_context=v2.technical_context,
        aggregate_graph_context=v2.aggregate_graph_context,
        participant_faq=[entry.model_copy(deep=True) for entry in v2.participant_faq],
    )
