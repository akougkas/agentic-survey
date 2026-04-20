from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from agentic_survey.domain.tools import GetUserInputOptions

__all__ = [
    "AxisCoverage",
    "BrainBIntent",
    "OutlinePatch",
    "OutlinePatchSection",
]

OutlinePatchOp = Literal["replace", "append", "remove"]


class OutlinePatchSection(BaseModel):
    """One targeted change Brain B wants the API to apply to the outline."""

    section: str
    op: OutlinePatchOp
    value: Any = None


class OutlinePatch(BaseModel):
    """A bundle of outline edits plus the rationale Brain B used to justify them.

    The API applies the sections in order, persists a new ``outline_revision``
    linked to the triggering designer_turn, and emits the appropriate SSE
    deltas. An empty ``sections`` list is a no-op patch (Brain B may still
    want to attach a summary without editing).
    """

    sections: list[OutlinePatchSection] = Field(default_factory=list)
    provenance: str = ""
    summary: str = ""


class AxisCoverage(BaseModel):
    """Brain B's self-scored completeness for one of the five Designer axes."""

    axis: str
    score: float = Field(ge=0.0, le=1.0)
    gap: str = ""


class BrainBIntent(BaseModel):
    """Inter-brain handoff payload emitted by Designer Brain B each turn.

    Brain A renders ``get_user_input`` verbatim. ``outline_patch`` is applied
    before the Brain A call so the prose can reference the new outline state.
    ``ready_for_review`` is advisory; the scientist still clicks the button.
    """

    active_axis: str
    axes_coverage: list[AxisCoverage] = Field(default_factory=list)
    question_intent: str
    get_user_input: GetUserInputOptions
    outline_patch: OutlinePatch | None = None
    ready_for_review: bool = False
    should_close: bool = False
    closing: bool = False
    retrieval_used: bool = False
    retrieval_chunks: list[str] = Field(default_factory=list)
