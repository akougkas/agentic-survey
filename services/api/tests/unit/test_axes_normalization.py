from __future__ import annotations

import asyncio
import json
from typing import Any

from agentic_survey.agents.brain_b_interviewer import run_brain_b_interviewer
from agentic_survey.agents.brain_b_loop import run_brain_b_with_tools
from agentic_survey.agents.tools.registry import ToolRegistry
from agentic_survey.domain.intent import AxisCoverage
from agentic_survey.domain.outline import OutlineArtifact, OutlineRubric
from agentic_survey.engine.session_policy import SessionSignals


class _ScriptedRouter:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def acompletion(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if not self._responses:
            raise RuntimeError("scripted router exhausted")
        return self._responses.pop(0)


def _completion(*, content: str | None = None) -> dict[str, Any]:
    return {"choices": [{"message": {"content": content, "tool_calls": None}}]}


def _intent_payload(
    *,
    axes_coverage: list[dict[str, Any]] | None = None,
    should_close: bool = False,
) -> dict[str, Any]:
    return {
        "active_axis": "R1",
        "axes_coverage": axes_coverage if axes_coverage is not None else [],
        "question_intent": "clarify",
        "get_user_input": {
            "question": "probe question?",
            "options": [
                "Option A",
                "Option B",
                "Discuss this more.",
            ],
            "allow_free_text": True,
        },
        "outline_patch": None,
        "ready_for_review": False,
        "should_close": should_close,
        "closing": False,
        "retrieval_used": False,
        "retrieval_chunks": [],
    }


def _run(
    *,
    payload: dict[str, Any],
    rubric_axes: list[str] | None,
    prior_axes_coverage: list[AxisCoverage] | None = None,
    close_guard_axes: list[str] | None = None,
):
    router = _ScriptedRouter([_completion(content=json.dumps(payload))])
    return asyncio.run(
        run_brain_b_with_tools(
            surface="interviewer",
            system_context=[],
            transcript_tail=[],
            registry=ToolRegistry(),
            router=router,
            rubric_axes=rubric_axes,
            prior_axes_coverage=prior_axes_coverage,
            close_guard_axes=close_guard_axes,
        )
    )


def test_axes_normalizer_zero_fills_from_rubric_when_no_prior() -> None:
    result = _run(
        payload=_intent_payload(axes_coverage=[]),
        rubric_axes=["R1 — Foo", "R2 — Bar", "R3 — Baz"],
    )
    axes = result.intent.axes_coverage
    assert [entry.axis for entry in axes] == ["R1", "R2", "R3"]
    assert all(entry.score == 0.0 for entry in axes)


def test_axes_normalizer_carries_forward_prior_when_emission_empty() -> None:
    prior = [
        AxisCoverage(axis="R1", score=0.6),
        AxisCoverage(axis="R2", score=0.3),
    ]
    result = _run(
        payload=_intent_payload(axes_coverage=[]),
        rubric_axes=["R1 — Foo", "R2 — Bar"],
        prior_axes_coverage=prior,
    )
    axes = result.intent.axes_coverage
    scores = {entry.axis: entry.score for entry in axes}
    assert scores == {"R1": 0.6, "R2": 0.3}


def test_axes_normalizer_enforces_monotonicity() -> None:
    prior = [AxisCoverage(axis="R1", score=0.5)]
    result = _run(
        payload=_intent_payload(
            axes_coverage=[{"axis": "R1", "score": 0.2, "gap": ""}],
        ),
        rubric_axes=["R1 — Foo"],
        prior_axes_coverage=prior,
    )
    assert result.intent.axes_coverage[0].axis == "R1"
    assert result.intent.axes_coverage[0].score == 0.5


def test_axes_normalizer_accepts_upgrade_against_prior() -> None:
    prior = [AxisCoverage(axis="R1", score=0.5)]
    result = _run(
        payload=_intent_payload(
            axes_coverage=[{"axis": "R1", "score": 0.8, "gap": ""}],
        ),
        rubric_axes=["R1 — Foo"],
        prior_axes_coverage=prior,
    )
    assert result.intent.axes_coverage[0].score == 0.8


def test_axes_normalizer_matches_full_label_against_r_code() -> None:
    result = _run(
        payload=_intent_payload(
            axes_coverage=[
                {"axis": "R1 — Foo long label", "score": 0.4, "gap": ""}
            ],
        ),
        rubric_axes=["R1 — Foo long label"],
    )
    assert len(result.intent.axes_coverage) == 1
    entry = result.intent.axes_coverage[0]
    assert entry.axis == "R1"
    assert entry.score == 0.4


def test_close_guard_flips_should_close_when_R8_zero() -> None:
    axes = [
        {"axis": f"R{n}", "score": 0.5, "gap": ""} for n in range(1, 8)
    ]
    axes.append({"axis": "R8", "score": 0.0, "gap": ""})
    result = _run(
        payload=_intent_payload(axes_coverage=axes, should_close=True),
        rubric_axes=[f"R{n}" for n in range(1, 9)],
        close_guard_axes=["R8"],
    )
    assert result.intent.should_close is False


def test_close_guard_leaves_should_close_true_when_R8_nonzero() -> None:
    axes = [
        {"axis": f"R{n}", "score": 0.5, "gap": ""} for n in range(1, 8)
    ]
    axes.append({"axis": "R8", "score": 0.3, "gap": ""})
    result = _run(
        payload=_intent_payload(axes_coverage=axes, should_close=True),
        rubric_axes=[f"R{n}" for n in range(1, 9)],
        close_guard_axes=["R8"],
    )
    assert result.intent.should_close is True


def test_close_guard_is_inert_when_not_configured() -> None:
    axes = [{"axis": "R8", "score": 0.0, "gap": ""}]
    result = _run(
        payload=_intent_payload(axes_coverage=axes, should_close=True),
        rubric_axes=None,
        close_guard_axes=None,
    )
    assert result.intent.should_close is True


async def _empty_search(query: str, k: int, mode: str = "hybrid") -> list[dict[str, Any]]:
    return []


def _interviewer_axes_payload(*, should_close: bool) -> dict[str, Any]:
    axes = [
        {"axis": f"R{n}", "score": 0.5, "gap": ""} for n in range(1, 8)
    ]
    axes.append({"axis": "R8", "score": 0.0, "gap": ""})
    return _intent_payload(axes_coverage=axes, should_close=should_close)


def test_interviewer_derives_close_guard_from_outline_rubric() -> None:
    outline = OutlineArtifact(
        axes=[f"R{n} — Foo" for n in range(1, 9)],
        rubric=OutlineRubric(mandatory_close_axes=["R8"]),
    )
    router = _ScriptedRouter(
        [_completion(content=json.dumps(_interviewer_axes_payload(should_close=True)))]
    )
    intent = asyncio.run(
        run_brain_b_interviewer(
            outline=outline,
            transcript_tail=[],
            session_signals=SessionSignals(),
            router=router,
            search_knowledge=_empty_search,
            list_grounding_sources=lambda: [],
            graph_neighborhood=None,
        )
    )
    assert intent.should_close is False


def test_interviewer_no_close_guard_when_rubric_empty() -> None:
    outline = OutlineArtifact(
        axes=[f"R{n} — Foo" for n in range(1, 9)],
        rubric=OutlineRubric(),
    )
    router = _ScriptedRouter(
        [_completion(content=json.dumps(_interviewer_axes_payload(should_close=True)))]
    )
    intent = asyncio.run(
        run_brain_b_interviewer(
            outline=outline,
            transcript_tail=[],
            session_signals=SessionSignals(),
            router=router,
            search_knowledge=_empty_search,
            list_grounding_sources=lambda: [],
            graph_neighborhood=None,
        )
    )
    assert intent.should_close is True
