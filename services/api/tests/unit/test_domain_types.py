from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentic_survey.domain.intent import (
    AxisCoverage,
    BrainBIntent,
    OutlinePatch,
    OutlinePatchSection,
)
from agentic_survey.domain.outline import (
    DecisionGate,
    MicroFormField,
    OutlineArtifact,
    OutlineRubric,
    ParticipantFAQEntry,
    RiskEntry,
)
from agentic_survey.domain.observation import MethodObservation
from agentic_survey.domain.tools import DISCUSS_MORE_OPTION, GetUserInputOptions


def _valid_chips() -> GetUserInputOptions:
    return GetUserInputOptions(
        question="What should the first axis commit to?",
        options=[
            "Lock the research question to trust calibration across adopters.",
            "Lock it to validation routines across domains.",
            "Lock it to leverage-vs-theater lifecycle questions.",
            DISCUSS_MORE_OPTION,
        ],
    )


def test_get_user_input_options_accepts_three_to_five_chips_ending_in_discuss_more() -> None:
    payload = _valid_chips()
    assert len(payload.options) == 4
    assert payload.options[-1] == DISCUSS_MORE_OPTION
    assert payload.allow_free_text is True


def test_get_user_input_options_rejects_wrong_last_option() -> None:
    with pytest.raises(ValidationError):
        GetUserInputOptions(
            question="?",
            options=["one", "two", "three", "four"],
        )


def test_get_user_input_options_rejects_too_few_options() -> None:
    """A single-option payload is below the closing-turn floor of 2."""
    with pytest.raises(ValidationError):
        GetUserInputOptions(
            question="?",
            options=[DISCUSS_MORE_OPTION],
        )


def test_get_user_input_options_accepts_closing_pair() -> None:
    """Closing turns collapse to two options: a closing affordance + Discuss this more."""
    payload = GetUserInputOptions(
        question="?",
        options=["End conversation", DISCUSS_MORE_OPTION],
    )
    assert payload.options == ["End conversation", DISCUSS_MORE_OPTION]


def test_outline_artifact_defaults_are_empty_and_permissive() -> None:
    outline = OutlineArtifact()
    assert outline.research_question == ""
    assert outline.sampling_frame == ""
    assert outline.axes == []
    assert outline.objectives == []
    assert outline.probes == []
    assert outline.risk_register == []
    assert outline.grounding_sources_approved == []
    assert outline.suggested_search_queries == []
    assert outline.micro_form_schema == []
    assert outline.participant_faq == []
    assert outline.persona_hints == {}
    assert outline.decision_gate is None
    assert outline.min_n == 6
    assert outline.max_n == 40
    assert isinstance(outline.rubric, OutlineRubric)
    assert outline.rubric.coverage_dimensions == []
    assert outline.rubric.risk_checks == []


def test_outline_artifact_round_trips_rich_fields() -> None:
    outline = OutlineArtifact(
        research_question="Does trust calibration separate durable adopters from churners?",
        sampling_frame="Adopters with inclusion criteria stipulating two years of hands-on use.",
        exclusion_criteria="Vendors pitching the tools they build.",
        publication_intent="hypothesis_test",
        axes=["research_question", "sampling_frame", "risk_map"],
        objectives=["probe the axis"],
        probes=["walk me through a concrete moment"],
        risk_register=[
            RiskEntry(
                risk="leading prompt on effectiveness",
                mitigation="ask for failures first",
            )
        ],
        grounding_sources_approved=["ksrc-seed"],
        readiness_rationale="all five axes are above 0.75",
        decision_gate=DecisionGate(gate="launch", rationale="axes cleared"),
        suggested_search_queries=["trust calibration research"],
        min_n=5,
        max_n=20,
        rubric=OutlineRubric(
            coverage_dimensions=["concrete workflow moment"],
            risk_checks=["no leading prompts"],
        ),
        freshness_query="trust calibration research",
        persona_hints={"name": "Mira"},
        consent_language="named or anonymous",
        micro_form_schema=[MicroFormField(key="discipline", label="Discipline")],
        scientist_summary="quick brief",
        study_context="context",
        market_context="market",
        technical_context="tech",
        aggregate_graph_context="graph",
        participant_faq=[
            ParticipantFAQEntry(
                key="scope",
                question="what is this?",
                answer="a study",
                tags=["scope"],
            )
        ],
    )
    restored = OutlineArtifact.model_validate(outline.model_dump())
    assert restored == outline


def test_brain_b_intent_round_trips_through_json() -> None:
    intent = BrainBIntent(
        active_axis="research_question",
        axes_coverage=[
            AxisCoverage(axis="research_question", score=0.4, gap="topic not yet a question"),
            AxisCoverage(axis="sampling_frame", score=0.2, gap="no population pinned"),
        ],
        question_intent="turn the topic into a falsifiable sentence",
        get_user_input=_valid_chips(),
        outline_patch=OutlinePatch(
            sections=[
                OutlinePatchSection(
                    section="research_question",
                    op="replace",
                    value="Does trust calibration separate durable adopters from churners?",
                )
            ],
            provenance="scientist utterance turn 3",
            summary="locked axis 1",
        ),
        ready_for_review=False,
        retrieval_used=True,
        retrieval_chunks=["chunk:42", "chunk:91"],
        retrieval_audit_ids=["retaudit:1"],
    )
    serialized = intent.model_dump_json()
    restored = BrainBIntent.model_validate_json(serialized)
    assert restored == intent
    assert restored.get_user_input.options[-1] == DISCUSS_MORE_OPTION
    assert restored.outline_patch is not None
    assert restored.outline_patch.sections[0].op == "replace"
    assert restored.retrieval_audit_ids == ["retaudit:1"]


def test_decision_gate_and_risk_entry_shapes() -> None:
    gate = DecisionGate(gate="launch", rationale="all five axes cleared self-scoring floor")
    risk = RiskEntry(risk="leading prompt on effectiveness", mitigation="ask for failures first")
    outline = OutlineArtifact(decision_gate=gate, risk_register=[risk])
    assert outline.decision_gate == gate
    assert outline.risk_register[0].mitigation == "ask for failures first"


def test_method_observation_tags_are_capped_by_truncation() -> None:
    observation = MethodObservation(
        id="mobs-test",
        session_id="session-test",
        campaign_id="campaign-test",
        author="operator",
        body="probe felt thin",
        tags=[f"t{i}" for i in range(12)],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert observation.tags == ["t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7"]
