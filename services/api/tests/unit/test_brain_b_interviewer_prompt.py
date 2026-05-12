from __future__ import annotations

import asyncio
import json
from typing import Any

from agentic_survey.agents.brain_b_interviewer import (
    run_brain_b_interviewer,
    shortlist_question_bank_for_prompt,
)
from agentic_survey.domain.intent import AxisCoverage, QuestionCoverage
from agentic_survey.domain.outline import OutlineArtifact, SurveyQuestion
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


async def _empty_search(query: str, k: int, mode: str = "hybrid") -> list[dict[str, Any]]:
    return []


def _completion(*, content: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": content, "tool_calls": None}}]}


def _intent_payload() -> dict[str, Any]:
    return {
        "active_axis": "R1",
        "axes_coverage": [],
        "question_coverage": [],
        "question_intent": "Ask for the most recent concrete workflow moment.",
        "get_user_input": {
            "question": "What happened most recently?",
            "options": ["In the last run...", "The handoff broke when...", "Discuss this more."],
            "allow_free_text": True,
        },
        "should_close": False,
        "retrieval_used": False,
        "retrieval_chunks": [],
    }


def _question(question_id: str, axis: str, *, tier: str = "A") -> SurveyQuestion:
    return SurveyQuestion(
        id=question_id,
        tier=tier,
        prompt=f"Prompt for {question_id}",
        axis_tag=axis,
    )


def test_question_shortlist_prefers_continuations_and_low_coverage_axes() -> None:
    questions = [_question(f"Q{index}", f"R{index}") for index in range(1, 11)]

    shortlist = shortlist_question_bank_for_prompt(
        questions,
        prior_question_coverage=[
            QuestionCoverage(question_id="Q10", status="targeting"),
            QuestionCoverage(question_id="Q2", status="satisfied"),
        ],
        prior_axes_coverage=[
            AxisCoverage(axis="R1", score=0.8),
            AxisCoverage(axis="R2", score=0.8),
            AxisCoverage(axis="R3", score=0.0),
        ],
        rubric_axes=[f"R{index} — Axis" for index in range(1, 11)],
        active_axis_prefix="R3",
        limit=4,
    )

    assert [question.id for question in shortlist] == ["Q10", "Q3", "Q4", "Q5"]


def test_interviewer_prompt_omits_full_bank_and_sends_shortlist() -> None:
    outline = OutlineArtifact(
        axes=[f"R{index} — Axis" for index in range(1, 11)],
        question_bank=[_question(f"Q{index}", f"R{index}") for index in range(1, 11)],
    )
    router = _ScriptedRouter([_completion(content=json.dumps(_intent_payload()))])

    asyncio.run(
        run_brain_b_interviewer(
            outline=outline,
            transcript_tail=[],
            session_signals=SessionSignals(),
            router=router,
            search_knowledge=_empty_search,
            list_grounding_sources=lambda: [],
            graph_neighborhood=None,
            enable_tools=False,
        )
    )

    prompt_text = "\n".join(
        message["content"] for message in router.calls[0]["messages"] if message["role"] == "system"
    )
    assert "Question shortlist" in prompt_text
    assert '"question_bank_count": 10' in prompt_text
    assert '"id": "Q8"' in prompt_text
    assert '"id": "Q9"' not in prompt_text
    assert '"id": "Q10"' not in prompt_text
    assert '"question_bank":' not in prompt_text
