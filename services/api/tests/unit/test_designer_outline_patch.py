from __future__ import annotations

from agentic_survey.agents.designer import apply_outline_patch, is_ready_for_review
from agentic_survey.domain.intent import OutlinePatch, OutlinePatchSection
from agentic_survey.domain.outline import OutlineArtifact


def test_apply_outline_patch_unwraps_text_object_for_string_field() -> None:
    outline = OutlineArtifact(
        sampling_frame="eligible users include operators who ran the workflow",
        exclusion_criteria="none - intentional",
        publication_intent="internal decision memo",
        axes=["adoption", "friction", "risk"],
        probes=["recent moment", "failure mode", "decision point"],
        risk_register=[{"risk": "leading prompt", "mitigation": "ask for examples"}],
    )
    patch = OutlinePatch(
        sections=[
            OutlinePatchSection(
                section="research_question",
                op="replace",
                value={
                    "text": "Does operational trust separate durable HPC AI adoption from short-lived trial usage?"
                },
            )
        ]
    )

    updated = apply_outline_patch(outline, patch)
    ready, unmet = is_ready_for_review(updated, brain_b_ready=True)

    assert updated.research_question == (
        "Does operational trust separate durable HPC AI adoption from short-lived trial usage?"
    )
    assert ready is True
    assert unmet == []


def test_apply_outline_patch_skips_ambiguous_object_for_string_field() -> None:
    outline = OutlineArtifact(research_question="Original question text that stays intact")
    patch = OutlinePatch(
        sections=[
            OutlinePatchSection(
                section="research_question",
                op="replace",
                value={
                    "claim": "Does trust matter?",
                    "evidence": "Operator stories",
                },
            )
        ]
    )

    updated = apply_outline_patch(outline, patch)

    assert updated.research_question == "Original question text that stays intact"


def test_apply_outline_patch_validates_list_items_before_assignment() -> None:
    outline = OutlineArtifact(axes=["adoption"])
    patch = OutlinePatch(
        sections=[
            OutlinePatchSection(
                section="axes",
                op="append",
                value=[
                    {"text": "operational trust"},
                    {"claim": "ambiguous", "evidence": "ignored"},
                    "workflow fit",
                ],
            )
        ]
    )

    updated = apply_outline_patch(outline, patch)

    assert updated.axes == ["adoption", "operational trust", "workflow fit"]
