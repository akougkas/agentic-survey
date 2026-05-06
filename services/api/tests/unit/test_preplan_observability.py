"""Tests for the preplan_status / preplan_inflight observability fields.

The cold-start eager Brain B warmup (M11.10) hands the foreground turn a
ready-made plan when it succeeds before the participant arrives. M11.11
makes the outcome of that race legible at the session level so an
operator inspecting a stalled-feeling launch can tell whether the
warmup landed, was skipped, or blew up.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agentic_survey.api import background_tasks as background_tasks_module
from agentic_survey.api.background_tasks import spawn_post_turn_bg, spawn_pre_plan_bg
from agentic_survey.domain.intent import BrainBIntent
from agentic_survey.domain.tools import GetUserInputOptions
from agentic_survey.engine import interview_loop as interview_loop_module
from agentic_survey.engine.event_bus import CampaignEventBus
from agentic_survey.engine.interview_loop import run_pre_plan_background
from agentic_survey.engine.retrieval_cache import RetrievalCache
from agentic_survey.repository import InMemoryRepository


class _StubRouter:
    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        return {"data": [{"embedding": [0.01] * 768} for _ in input]}

    async def acompletion(self, **kwargs: Any):
        async def _chunks():
            yield {"choices": [{"delta": {"content": "ok"}}]}

        return _chunks()


def _planned_intent() -> BrainBIntent:
    return BrainBIntent(
        active_axis="planned_axis",
        axes_coverage=[],
        question_intent="Ask the planned probe.",
        get_user_input=GetUserInputOptions(
            question="Planned probe question?",
            options=["Planned chip A", "Planned chip B", "Discuss this more."],
            allow_free_text=True,
        ),
        outline_patch=None,
        ready_for_review=False,
        should_close=False,
        closing=False,
        retrieval_used=False,
        retrieval_chunks=[],
    )


def _seed_session(repo: InMemoryRepository) -> tuple[Any, Any]:
    campaign = repo.create_campaign(title="Preplan harness", min_n=3, max_n=6)
    outline = campaign.outline.model_copy(deep=True)
    outline.axes = ["workflow"]
    repo.update_outline(campaign.id, outline, ready_for_review=True)
    campaign = repo.get_campaign(campaign.id)
    assert campaign is not None
    session = repo.start_interview_session(
        campaign_id=campaign.id,
        invite_id=None,
        consent_mode="anonymous",
        identity_label="",
        persona_snapshot={},
        pinned_endpoint="mini",
    )
    return campaign, session


def test_session_starts_with_pending_preplan_state() -> None:
    repo = InMemoryRepository()
    _, session = _seed_session(repo)
    fresh = repo.get_interview_session(session.id)
    assert fresh is not None
    assert fresh.preplan_status == "pending"
    assert fresh.preplan_error_detail is None
    assert fresh.preplan_inflight is False


def test_preplan_status_ready_after_successful_warmup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fast_brain_b(**_kwargs: Any) -> BrainBIntent:
        return _planned_intent()

    monkeypatch.setattr(interview_loop_module, "run_brain_b_interviewer", fast_brain_b)

    repo = InMemoryRepository()
    campaign, session = _seed_session(repo)
    repo.try_acquire_preplan_lock(session.id)

    asyncio.run(
        run_pre_plan_background(
            session_id=session.id,
            campaign_id=campaign.id,
            repository=repo,
            router=_StubRouter(),
            cache=RetrievalCache(),
            bus=CampaignEventBus(),
        )
    )

    final = repo.get_interview_session(session.id)
    assert final is not None
    assert final.preplan_status == "ready"
    assert final.preplan_error_detail is None
    assert final.preplan_inflight is False
    assert final.next_plan is not None


def test_preplan_status_late_skipped_when_participant_turn_lands_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def slow_brain_b(**_kwargs: Any) -> BrainBIntent:
        await asyncio.sleep(0)
        return _planned_intent()

    monkeypatch.setattr(interview_loop_module, "run_brain_b_interviewer", slow_brain_b)

    repo = InMemoryRepository()
    campaign, session = _seed_session(repo)
    repo.try_acquire_preplan_lock(session.id)
    repo.append_interview_turn(
        session.id,
        role="participant",
        content="Participant got there first.",
    )

    asyncio.run(
        run_pre_plan_background(
            session_id=session.id,
            campaign_id=campaign.id,
            repository=repo,
            router=_StubRouter(),
            cache=RetrievalCache(),
            bus=CampaignEventBus(),
        )
    )

    final = repo.get_interview_session(session.id)
    assert final is not None
    assert final.preplan_status == "late_skipped"
    assert final.preplan_error_detail is None
    assert final.preplan_inflight is False
    # The warmup must not overwrite a foreground-driven next_plan with stale
    # planning, so next_plan stays at whatever the participant turn produced
    # (None here, since this test stubs the foreground out entirely).
    assert final.next_plan is None


def test_preplan_status_failed_on_brain_b_exception_records_error_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom_brain_b(**_kwargs: Any) -> BrainBIntent:
        raise RuntimeError("dynamo unreachable")

    monkeypatch.setattr(interview_loop_module, "run_brain_b_interviewer", boom_brain_b)

    repo = InMemoryRepository()
    campaign, session = _seed_session(repo)
    repo.try_acquire_preplan_lock(session.id)

    asyncio.run(
        run_pre_plan_background(
            session_id=session.id,
            campaign_id=campaign.id,
            repository=repo,
            router=_StubRouter(),
            cache=RetrievalCache(),
            bus=CampaignEventBus(),
        )
    )

    final = repo.get_interview_session(session.id)
    assert final is not None
    assert final.preplan_status == "failed"
    assert final.preplan_error_detail is not None
    assert "dynamo unreachable" in final.preplan_error_detail
    assert final.preplan_inflight is False


def test_single_flight_back_to_back_dispatch_runs_brain_b_only_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two near-simultaneous dispatchers must collapse to one Brain B call.

    Invite redemption and ``POST /sessions/{sid}/start`` can both fire a
    pre-plan dispatch within the same request lifecycle. The DB-level
    ``preplan_inflight`` CAS guarantees only the first dispatcher
    actually plans; the second is a no-op.
    """
    call_count = 0

    async def slow_brain_b(**_kwargs: Any) -> BrainBIntent:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return _planned_intent()

    monkeypatch.setattr(interview_loop_module, "run_brain_b_interviewer", slow_brain_b)

    repo = InMemoryRepository()
    campaign, session = _seed_session(repo)
    bus = CampaignEventBus()

    async def main() -> None:
        first = spawn_pre_plan_bg(
            session_id=session.id,
            campaign_id=campaign.id,
            repository=repo,
            router=_StubRouter(),
            cache=RetrievalCache(),
            bus=bus,
        )
        second = spawn_pre_plan_bg(
            session_id=session.id,
            campaign_id=campaign.id,
            repository=repo,
            router=_StubRouter(),
            cache=RetrievalCache(),
            bus=bus,
        )
        assert first is not None
        assert second is None
        await first

    asyncio.run(main())

    assert call_count == 1
    final = repo.get_interview_session(session.id)
    assert final is not None
    assert final.preplan_status == "ready"
    assert final.preplan_inflight is False


def test_single_flight_can_re_dispatch_after_terminal_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second dispatcher succeeds once the first has released the lock."""
    call_count = 0

    async def fast_brain_b(**_kwargs: Any) -> BrainBIntent:
        nonlocal call_count
        call_count += 1
        return _planned_intent()

    monkeypatch.setattr(interview_loop_module, "run_brain_b_interviewer", fast_brain_b)

    repo = InMemoryRepository()
    campaign, session = _seed_session(repo)
    bus = CampaignEventBus()

    async def main() -> None:
        first = spawn_pre_plan_bg(
            session_id=session.id,
            campaign_id=campaign.id,
            repository=repo,
            router=_StubRouter(),
            cache=RetrievalCache(),
            bus=bus,
        )
        assert first is not None
        await first

        second = spawn_pre_plan_bg(
            session_id=session.id,
            campaign_id=campaign.id,
            repository=repo,
            router=_StubRouter(),
            cache=RetrievalCache(),
            bus=bus,
        )
        assert second is not None
        await second

    asyncio.run(main())

    assert call_count == 2


def test_post_turn_cancels_obsolete_preplan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()

    async def stuck_preplan(**_kwargs: Any) -> None:
        started.set()
        await asyncio.sleep(60)

    async def fast_post_turn(**_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(
        background_tasks_module,
        "run_pre_plan_background",
        stuck_preplan,
    )
    monkeypatch.setattr(
        background_tasks_module,
        "run_post_turn_background",
        fast_post_turn,
    )

    repo = InMemoryRepository()
    campaign, session = _seed_session(repo)
    bus = CampaignEventBus()

    async def main() -> None:
        preplan = spawn_pre_plan_bg(
            session_id=session.id,
            campaign_id=campaign.id,
            repository=repo,
            router=_StubRouter(),
            cache=RetrievalCache(),
            bus=bus,
        )
        assert preplan is not None
        await asyncio.wait_for(started.wait(), timeout=1)
        post_turn = spawn_post_turn_bg(
            session_id=session.id,
            campaign_id=campaign.id,
            participant_turn_id="participant-1",
            agent_turn_id="agent-1",
            repository=repo,
            router=_StubRouter(),
            validator=None,  # type: ignore[arg-type]
            cache=RetrievalCache(),
            bus=bus,
        )
        await post_turn
        cancelled = await asyncio.gather(preplan, return_exceptions=True)
        assert isinstance(cancelled[0], asyncio.CancelledError)

    asyncio.run(main())

    final = repo.get_interview_session(session.id)
    assert final is not None
    assert final.preplan_status == "late_skipped"
    assert final.preplan_inflight is False
