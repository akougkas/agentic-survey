"""Unit tests for ``_consecutive_active_axis_history``.

The helper walks a session's agent turns newest-first and returns the
prior active axis prefix and the count of consecutive prior agent turns
that stayed on it. The orchestrator passes both back to Brain B so the
planner can rotate before the server-side override fires.
"""

from __future__ import annotations

from agentic_survey.domain.intent import BrainBIntent
from agentic_survey.domain.tools import GetUserInputOptions
from agentic_survey.engine.interview_loop import _consecutive_active_axis_history
from agentic_survey.repository import InterviewSessionRecord, InterviewTurnRecord


def _agent_turn(idx: int, active_axis: str) -> InterviewTurnRecord:
    intent = BrainBIntent(
        active_axis=active_axis,
        axes_coverage=[],
        question_coverage=[],
        question_intent="probe",
        get_user_input=GetUserInputOptions(
            question="Q",
            options=["A", "B", "Discuss this more."],
            allow_free_text=True,
        ),
        outline_patch=None,
        ready_for_review=False,
        should_close=False,
        closing=False,
        retrieval_used=False,
        retrieval_chunks=[],
    )
    return InterviewTurnRecord(
        id=f"turn-agent-{idx}",
        session_id="session-x",
        role="agent",
        content="agent line",
        index=idx,
        validation=None,
        brain_b_intent=intent,
        get_user_input=intent.get_user_input,
        retrieval_audit_id=None,
        created_at="2026-05-04T00:00:00Z",
    )


def _participant_turn(idx: int) -> InterviewTurnRecord:
    return InterviewTurnRecord(
        id=f"turn-part-{idx}",
        session_id="session-x",
        role="participant",
        content="participant line",
        index=idx,
        validation=None,
        brain_b_intent=None,
        get_user_input=None,
        retrieval_audit_id=None,
        created_at="2026-05-04T00:00:00Z",
    )


def _session(turns: list[InterviewTurnRecord]) -> InterviewSessionRecord:
    return InterviewSessionRecord(
        id="session-x",
        campaign_id="campaign-x",
        invite_id=None,
        participant_token="tok",
        consent_mode="anonymous",
        identity_label="",
        persona_snapshot={},
        pinned_endpoint="mini",
        status="active",
        started_at="2026-05-04T00:00:00Z",
        updated_at="2026-05-04T00:00:00Z",
        turns=turns,
    )


def test_empty_session_returns_no_prior_axis() -> None:
    session = _session([])
    prefix, count = _consecutive_active_axis_history(session)
    assert prefix == ""
    assert count == 0


def test_single_agent_turn_returns_count_one() -> None:
    session = _session(
        [
            _agent_turn(0, "R1 — Lifecycle pain topology"),
            _participant_turn(1),
        ]
    )
    prefix, count = _consecutive_active_axis_history(session)
    assert prefix == "R1"
    assert count == 1


def test_two_consecutive_same_axis_turns_count_two() -> None:
    session = _session(
        [
            _agent_turn(0, "R1"),
            _participant_turn(1),
            _agent_turn(2, "R1 — Lifecycle pain topology"),
            _participant_turn(3),
        ]
    )
    prefix, count = _consecutive_active_axis_history(session)
    assert prefix == "R1"
    assert count == 2


def test_axis_break_resets_count() -> None:
    session = _session(
        [
            _agent_turn(0, "R1"),
            _participant_turn(1),
            _agent_turn(2, "R1"),
            _participant_turn(3),
            _agent_turn(4, "R3 — Handoffs"),
            _participant_turn(5),
        ]
    )
    prefix, count = _consecutive_active_axis_history(session)
    assert prefix == "R3"
    assert count == 1


def test_three_consecutive_same_axis_turns_count_three() -> None:
    session = _session(
        [
            _agent_turn(0, "R1"),
            _participant_turn(1),
            _agent_turn(2, "R1"),
            _participant_turn(3),
            _agent_turn(4, "R1 — Lifecycle"),
            _participant_turn(5),
        ]
    )
    prefix, count = _consecutive_active_axis_history(session)
    assert prefix == "R1"
    assert count == 3
