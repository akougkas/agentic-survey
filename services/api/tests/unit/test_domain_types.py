from __future__ import annotations

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
    OutlineArtifactV2,
    RiskEntry,
    from_v1,
    to_v1,
)
from agentic_survey.domain.tools import DISCUSS_MORE_OPTION, GetUserInputOptions
from agentic_survey.repository import (
    DEFAULT_MICRO_FORM_SCHEMA,
    DEFAULT_PERSONA_HINTS,
    DEFAULT_RUBRIC,
    OutlineArtifact,
)


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
    with pytest.raises(ValidationError):
        GetUserInputOptions(
            question="?",
            options=["only", DISCUSS_MORE_OPTION],
        )


def test_outline_artifact_v2_accepts_empty_defaults() -> None:
    outline = OutlineArtifactV2()
    assert outline.research_question == ""
    assert outline.axes == []
    assert outline.probes == []
    assert outline.risk_register == []
    assert outline.decision_gate is None
    assert outline.min_n == 6
    assert outline.max_n == 40


def test_outline_artifact_v2_preserves_legacy_fields_additively() -> None:
    legacy = OutlineArtifact(
        objectives=["probe the axis"],
        probes=["walk me through a concrete moment"],
        rubric=DEFAULT_RUBRIC,
        min_n=5,
        max_n=20,
        freshness_query="trust calibration research",
        persona_hints=dict(DEFAULT_PERSONA_HINTS),
        consent_language="named or anonymous",
        micro_form_schema=list(DEFAULT_MICRO_FORM_SCHEMA),
    )
    lifted = from_v1(legacy)
    assert lifted.suggested_search_queries == ["trust calibration research"]
    assert lifted.probes == legacy.probes
    assert lifted.persona_hints == DEFAULT_PERSONA_HINTS
    assert lifted.min_n == 5
    assert lifted.max_n == 20

    restored = to_v1(lifted)
    assert restored.objectives == legacy.objectives
    assert restored.probes == legacy.probes
    assert restored.freshness_query == legacy.freshness_query
    assert restored.persona_hints == legacy.persona_hints


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
    )
    serialized = intent.model_dump_json()
    restored = BrainBIntent.model_validate_json(serialized)
    assert restored == intent
    assert restored.get_user_input.options[-1] == DISCUSS_MORE_OPTION
    assert restored.outline_patch is not None
    assert restored.outline_patch.sections[0].op == "replace"


def test_decision_gate_and_risk_entry_shapes() -> None:
    gate = DecisionGate(gate="launch", rationale="all five axes cleared self-scoring floor")
    risk = RiskEntry(risk="leading prompt on effectiveness", mitigation="ask for failures first")
    outline = OutlineArtifactV2(decision_gate=gate, risk_register=[risk])
    assert outline.decision_gate == gate
    assert outline.risk_register[0].mitigation == "ask for failures first"
