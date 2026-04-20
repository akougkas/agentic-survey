from __future__ import annotations

from agentic_survey.agents.designer_v2 import is_ready_for_review
from agentic_survey.agents.readiness import (
    MAX_N_CEILING,
    MIN_AXES,
    MIN_PROBES,
    MIN_RISK_REGISTER,
    RESEARCH_QUESTION_MIN_CHARS,
    unmet_minimums,
)
from agentic_survey.domain.outline import DecisionGate, OutlineArtifactV2, RiskEntry


def _fully_populated() -> OutlineArtifactV2:
    return OutlineArtifactV2(
        research_question=(
            "Does trust calibration separate durable AI adopters from churners across research workflows?"
        ),
        sampling_frame=(
            "Domain scientists running their own pipelines; inclusion criteria require "
            "two years of hands-on tool use and one shipped analysis."
        ),
        exclusion_criteria="Industry AI researchers without a scientific domain affiliation.",
        publication_intent="hypothesis_test",
        axes=["research_question", "sampling_frame", "risk_map"],
        probes=[
            "Walk me through the last concrete moment an AI tool shaped your work.",
            "Where do you still stop to validate or reproduce the result?",
            "When does the tool sound more certain than the evidence warrants?",
        ],
        risk_register=[
            RiskEntry(
                risk="Early adopters rationalize",
                mitigation="Ask for the most recent concrete example, not the general story.",
            )
        ],
        readiness_rationale="All five axes are above 0.75 and the risk register has a mitigation.",
        decision_gate=DecisionGate(gate="launch", rationale="axes cleared"),
        min_n=6,
        max_n=24,
    )


def test_empty_outline_flags_every_minimum() -> None:
    unmet = unmet_minimums(OutlineArtifactV2())
    joined = " ".join(unmet)
    assert len(unmet) >= 7
    assert "Research question is missing" in joined
    assert "Sampling frame is empty" in joined
    assert "Exclusion criteria are empty" in joined
    assert "Publication intent is not set" in joined
    assert "Axes of inquiry are too few" in joined
    assert "Probes are too few" in joined
    assert "Risk register is empty" in joined


def test_fully_populated_outline_passes_hard_floor() -> None:
    outline = _fully_populated()
    assert unmet_minimums(outline) == []


def test_partial_outline_surfaces_only_missing_items() -> None:
    outline = _fully_populated()
    outline.risk_register = []
    outline.axes = outline.axes[:2]
    unmet = unmet_minimums(outline)
    assert unmet == [
        "Axes of inquiry are too few — expand to at least three.",
        "Risk register is empty — name at least one confound and its mitigation.",
    ]


def test_sampling_frame_must_mention_inclusion_criteria() -> None:
    outline = _fully_populated()
    outline.sampling_frame = "Anyone interested in AI tools."
    unmet = unmet_minimums(outline)
    assert any("inclusion criteria" in msg for msg in unmet)


def test_research_question_minimum_character_floor() -> None:
    outline = _fully_populated()
    outline.research_question = "x" * (RESEARCH_QUESTION_MIN_CHARS - 1)
    unmet = unmet_minimums(outline)
    assert any("Research question is too thin" in msg for msg in unmet)


def test_sample_bound_invariants() -> None:
    outline = _fully_populated()
    outline.min_n = 10
    outline.max_n = 5
    unmet = unmet_minimums(outline)
    assert any("inverted" in msg for msg in unmet)

    outline.min_n = 1
    outline.max_n = MAX_N_CEILING + 1
    unmet = unmet_minimums(outline)
    assert any(f"exceeds {MAX_N_CEILING}" in msg for msg in unmet)


def test_designer_is_ready_for_review_combines_hard_floor_and_brain_b() -> None:
    good = _fully_populated()
    ready, unmet = is_ready_for_review(good, brain_b_ready=True)
    assert ready is True
    assert unmet == []

    ready, unmet = is_ready_for_review(good, brain_b_ready=False)
    assert ready is False
    assert unmet == []

    empty = OutlineArtifactV2()
    ready, unmet = is_ready_for_review(empty, brain_b_ready=True)
    assert ready is False
    assert len(unmet) >= 7


def test_minimum_constants_match_documentation() -> None:
    assert MIN_AXES == 3
    assert MIN_PROBES == 3
    assert MIN_RISK_REGISTER == 1
    assert RESEARCH_QUESTION_MIN_CHARS == 40
