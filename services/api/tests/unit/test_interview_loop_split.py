"""Foreground + background split for ``run_interview_turn``.

The foreground streams Brain A and returns; the background task spawned
by the HTTP handler runs Validator → graph → Brain B plan. These tests
verify the invariants of that split without involving live LLMs:

- Foreground does not wait on the background (test 1).
- Background failures are isolated and annotated on the agent turn
  (test 2).
- Scaffold intent drives Brain A when ``session.next_plan`` is empty
  (test 3).
- A populated ``session.next_plan`` is consumed verbatim by Brain A
  (test 4).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator

import pytest

from agentic_survey.agents.validator import ValidationResult
from agentic_survey.domain.intent import BrainBIntent
from agentic_survey.domain.tools import GetUserInputOptions
from agentic_survey.engine import interview_loop as interview_loop_module
from agentic_survey.engine.event_bus import CampaignEventBus
from agentic_survey.engine.interview_loop import (
    run_interview_turn,
    run_post_turn_background,
    run_pre_plan_background,
)
from agentic_survey.engine.retrieval_cache import RetrievalCache
from agentic_survey.domain.outline import SurveyQuestion
from agentic_survey.repository import InMemoryRepository


# ---------- Fixtures shared across tests ----------


class _StubRouter:
    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        return {"data": [{"embedding": [0.01] * 768} for _ in input]}

    async def acompletion(self, **kwargs: Any):
        async def _chunks():
            yield {"choices": [{"delta": {"content": "ok"}}]}

        return _chunks()


class _PassValidator:
    async def validate(self, **kwargs: Any) -> ValidationResult:
        return ValidationResult(
            coverage_score=0.4,
            quality_score=0.4,
            follow_up_needed=False,
            follow_up_reason="",
            is_spam=False,
            extracted_concepts=[],
            extracted_relations=[],
        )


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
        retrieval_used=True,
        retrieval_chunks=["chunk-1"],
    )


def _install_fast_brain_a(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_stream(**kwargs: Any) -> AsyncIterator[str]:
        for token in ("fake ", "reply"):
            yield token

    def _factory(**kwargs: Any) -> AsyncIterator[str]:
        return fake_stream(**kwargs)

    monkeypatch.setattr(interview_loop_module, "stream_brain_a", _factory)


def _seed_live_session(repo: InMemoryRepository, *, axes: list[str] | None = None):
    campaign = repo.create_campaign(title="Split harness", min_n=3, max_n=6)
    if axes is not None:
        outline = campaign.outline.model_copy(deep=True)
        outline.axes = list(axes)
        outline.probes = [
            "Tell me about a recent moment",
            "What changed after that",
        ]
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
    repo.append_interview_turn(
        session.id,
        role="agent",
        content="Opener probe goes here.",
    )
    return campaign, session


def _seed_retrieval_corpus(repo: InMemoryRepository, campaign_id: str) -> str:
    source = repo.create_knowledge_source(
        campaign_id=campaign_id,
        kind="raw_text",
        title="Operations notes",
        hash_value="ops-notes",
        status="approved",
    )
    chunk = repo.create_knowledge_chunk(
        campaign_id=campaign_id,
        source_id=source.id,
        content="The archive queue failed during beamline handoff.",
        position=0,
        char_start=0,
        char_end=50,
        approved=True,
    )
    return chunk.id


# ---------- Test 1: foreground returns before background completes ----------


def test_foreground_returns_before_slow_background_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fast_brain_a(monkeypatch)

    async def slow_brain_b(**kwargs: Any) -> BrainBIntent:
        await asyncio.sleep(1.2)
        return _planned_intent()

    monkeypatch.setattr(interview_loop_module, "run_brain_b_interviewer", slow_brain_b)

    repo = InMemoryRepository()
    campaign, session = _seed_live_session(repo, axes=["concrete_moments"])
    bus = CampaignEventBus()

    async def main() -> None:
        t0 = time.monotonic()
        result = await run_interview_turn(
            session_id=session.id,
            participant_content="We use code review often.",
            chip_selected=None,
            repository=repo,
            validator=_PassValidator(),
            router=_StubRouter(),
            cache=RetrievalCache(),
        )
        elapsed = time.monotonic() - t0
        # Foreground must not wait on the background's slow Brain B.
        assert elapsed < 0.6, f"foreground blocked for {elapsed:.2f}s"
        assert result.agent_turn is not None
        assert result.participant_turn is not None

        # Spawn the background the way sessions.py does and let it run.
        task = asyncio.create_task(
            run_post_turn_background(
                session_id=session.id,
                campaign_id=campaign.id,
                participant_turn_id=result.participant_turn.id,
                agent_turn_id=result.agent_turn.id,
                repository=repo,
                router=_StubRouter(),
                validator=_PassValidator(),
                cache=RetrievalCache(),
                bus=bus,
            )
        )
        await asyncio.wait_for(task, timeout=4)

    asyncio.run(main())

    refreshed = repo.get_interview_session(session.id)
    assert refreshed is not None
    assert refreshed.next_plan is not None
    assert refreshed.next_plan.active_axis == "planned_axis"


def test_brain_b_retrieval_audit_links_to_rendered_agent_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fast_brain_a(monkeypatch)

    async def brain_b_with_retrieval(**kwargs: Any) -> BrainBIntent:
        hits = await kwargs["search_knowledge"]("archive queue", 2, mode="bm25")
        intent = _planned_intent()
        return intent.model_copy(
            update={
                "retrieval_chunks": [hit["chunk_id"] for hit in hits],
                "retrieval_used": bool(hits),
            }
        )

    monkeypatch.setattr(interview_loop_module, "run_brain_b_interviewer", brain_b_with_retrieval)

    repo = InMemoryRepository()
    campaign, session = _seed_live_session(repo, axes=["workflow"])
    expected_chunk_id = _seed_retrieval_corpus(repo, campaign.id)
    bus = CampaignEventBus()

    async def main() -> None:
        first = await run_interview_turn(
            session_id=session.id,
            participant_content="The queue failed before transfer completed.",
            chip_selected=None,
            repository=repo,
            validator=_PassValidator(),
            router=_StubRouter(),
            cache=RetrievalCache(),
        )
        assert first.agent_turn is not None
        assert first.participant_turn is not None

        await run_post_turn_background(
            session_id=session.id,
            campaign_id=campaign.id,
            participant_turn_id=first.participant_turn.id,
            agent_turn_id=first.agent_turn.id,
            repository=repo,
            router=_StubRouter(),
            validator=_PassValidator(),
            cache=RetrievalCache(),
            bus=bus,
        )

        planned = repo.get_interview_session(session.id)
        assert planned is not None
        assert planned.next_plan is not None
        assert planned.next_plan.retrieval_chunks == [expected_chunk_id]
        assert len(planned.next_plan.retrieval_audit_ids) == 1
        audit_id = planned.next_plan.retrieval_audit_ids[0]
        audit = repo.get_retrieval_audit(audit_id)
        assert audit is not None
        assert audit.query == "archive queue"
        assert audit.chunk_ids == [expected_chunk_id]

        second = await run_interview_turn(
            session_id=session.id,
            participant_content="That handoff delayed users for hours.",
            chip_selected=None,
            repository=repo,
            validator=_PassValidator(),
            router=_StubRouter(),
            cache=RetrievalCache(),
        )
        assert second.agent_turn is not None
        assert second.agent_turn.retrieval_audit_id == audit_id
        assert second.agent_turn.brain_b_intent is not None
        assert second.agent_turn.brain_b_intent.retrieval_audit_ids == [audit_id]

    asyncio.run(main())
    planned_envelopes = [
        env for env in bus.replay(campaign.id, since=-1) if env.name == "brain_b_planned"
    ]
    assert len(planned_envelopes) == 1
    assert planned_envelopes[0].data["session_id"] == session.id


# ---------- Test 2: background failure is isolated ----------


def test_background_failure_marks_agent_turn_and_does_not_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fast_brain_a(monkeypatch)

    async def failing_brain_b(**kwargs: Any) -> BrainBIntent:
        raise RuntimeError("injected brain-b failure")

    monkeypatch.setattr(interview_loop_module, "run_brain_b_interviewer", failing_brain_b)

    repo = InMemoryRepository()
    campaign, session = _seed_live_session(repo, axes=["concrete_moments"])
    bus = CampaignEventBus()

    async def main() -> None:
        result = await run_interview_turn(
            session_id=session.id,
            participant_content="A substantive answer.",
            chip_selected=None,
            repository=repo,
            validator=_PassValidator(),
            router=_StubRouter(),
            cache=RetrievalCache(),
        )
        assert result.agent_turn is not None
        assert result.participant_turn is not None

        task = asyncio.create_task(
            run_post_turn_background(
                session_id=session.id,
                campaign_id=campaign.id,
                participant_turn_id=result.participant_turn.id,
                agent_turn_id=result.agent_turn.id,
                repository=repo,
                router=_StubRouter(),
                validator=_PassValidator(),
                cache=RetrievalCache(),
                bus=bus,
            )
        )
        # The background MUST NOT re-raise; wait should complete without error.
        done, _ = await asyncio.wait({task}, timeout=5)
        assert task in done
        # And the task itself should show no unhandled exception.
        assert task.exception() is None
        return result.agent_turn.id

    agent_turn_id = asyncio.run(main())

    refreshed = repo.get_interview_session(session.id)
    assert refreshed is not None
    agent_turn = next(turn for turn in refreshed.turns if turn.id == agent_turn_id)
    assert agent_turn.validation is not None
    assert agent_turn.validation.get("background_failed") is True


# ---------- Test 3: scaffold mode fires when next_plan is None ----------


def test_scaffold_mode_when_no_next_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fast_brain_a(monkeypatch)

    async def never_run_brain_b(**kwargs: Any) -> BrainBIntent:
        raise AssertionError("foreground must not call Brain B")

    monkeypatch.setattr(interview_loop_module, "run_brain_b_interviewer", never_run_brain_b)

    repo = InMemoryRepository()
    _, session = _seed_live_session(repo, axes=["concrete_moments"])
    # Explicitly confirm the plan is empty.
    refreshed = repo.get_interview_session(session.id)
    assert refreshed is not None and refreshed.next_plan is None

    async def main() -> None:
        return await run_interview_turn(
            session_id=session.id,
            participant_content="Substantive answer with no pre-plan available.",
            chip_selected=None,
            repository=repo,
            validator=_PassValidator(),
            router=_StubRouter(),
            cache=RetrievalCache(),
        )

    result = asyncio.run(main())

    assert result.agent_turn is not None
    intent = result.agent_turn.brain_b_intent
    assert intent is not None
    assert intent.retrieval_used is False
    assert intent.retrieval_chunks == []
    options = list(intent.get_user_input.options)
    assert options[-1] == "Discuss this more."
    assert len(options) >= 2
    assert result.agent_turn.validation == {"planner_source": "scaffold"}


# ---------- Test 4: populated next_plan wins over scaffold ----------


def test_populated_next_plan_is_rendered_not_scaffold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fast_brain_a(monkeypatch)

    async def never_run_brain_b(**kwargs: Any) -> BrainBIntent:
        raise AssertionError("foreground must not call Brain B")

    monkeypatch.setattr(interview_loop_module, "run_brain_b_interviewer", never_run_brain_b)

    repo = InMemoryRepository()
    _, session = _seed_live_session(repo, axes=["concrete_moments"])
    repo.update_next_plan(session.id, _planned_intent())

    async def main() -> None:
        return await run_interview_turn(
            session_id=session.id,
            participant_content="Substantive answer; a plan is waiting.",
            chip_selected=None,
            repository=repo,
            validator=_PassValidator(),
            router=_StubRouter(),
            cache=RetrievalCache(),
        )

    result = asyncio.run(main())

    assert result.agent_turn is not None
    intent = result.agent_turn.brain_b_intent
    assert intent is not None
    assert intent.active_axis == "planned_axis"
    assert intent.retrieval_used is True
    assert intent.retrieval_chunks == ["chunk-1"]
    assert result.agent_turn.validation == {"planner_source": "brain_b"}
    # Plan should be consumed on read so a failed future background cannot
    # render a stale probe.
    refreshed = repo.get_interview_session(session.id)
    assert refreshed is not None
    assert refreshed.next_plan is None


def test_stale_post_turn_background_skips_brain_b_planning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fast_brain_a(monkeypatch)
    calls = 0

    async def brain_b_should_not_run(**kwargs: Any) -> BrainBIntent:
        nonlocal calls
        calls += 1
        return _planned_intent()

    monkeypatch.setattr(interview_loop_module, "run_brain_b_interviewer", brain_b_should_not_run)

    repo = InMemoryRepository()
    campaign, session = _seed_live_session(repo, axes=["workflow"])
    bus = CampaignEventBus()

    async def main() -> str:
        first = await run_interview_turn(
            session_id=session.id,
            participant_content="The first answer names the archive queue.",
            chip_selected=None,
            repository=repo,
            validator=_PassValidator(),
            router=_StubRouter(),
            cache=RetrievalCache(),
        )
        assert first.agent_turn is not None
        assert first.participant_turn is not None
        await run_interview_turn(
            session_id=session.id,
            participant_content="The newer answer arrived before the old plan finished.",
            chip_selected=None,
            repository=repo,
            validator=_PassValidator(),
            router=_StubRouter(),
            cache=RetrievalCache(),
        )
        await run_post_turn_background(
            session_id=session.id,
            campaign_id=campaign.id,
            participant_turn_id=first.participant_turn.id,
            agent_turn_id=first.agent_turn.id,
            repository=repo,
            router=_StubRouter(),
            validator=_PassValidator(),
            cache=RetrievalCache(),
            bus=bus,
        )
        return first.participant_turn.id

    first_participant_id = asyncio.run(main())

    refreshed = repo.get_interview_session(session.id)
    assert refreshed is not None
    assert refreshed.next_plan is None
    assert calls == 0
    first_participant = next(turn for turn in refreshed.turns if turn.id == first_participant_id)
    assert first_participant.validation is not None
    assert first_participant.validation["coverage_score"] == 0.4
    planned_envelopes = [
        env for env in bus.replay(campaign.id, since=-1) if env.name == "brain_b_planned"
    ]
    assert planned_envelopes == []


def test_post_turn_background_skips_stale_plan_write_after_brain_b_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fast_brain_a(monkeypatch)
    repo = InMemoryRepository()
    campaign, session = _seed_live_session(repo, axes=["workflow"])
    bus = CampaignEventBus()

    async def brain_b_adds_newer_participant(**kwargs: Any) -> BrainBIntent:
        repo.append_interview_turn(
            session.id,
            role="participant",
            content="A newer participant turn landed while Brain B was planning.",
            validation={"pending_validation": True},
        )
        return _planned_intent()

    monkeypatch.setattr(interview_loop_module, "run_brain_b_interviewer", brain_b_adds_newer_participant)

    async def main() -> None:
        first = await run_interview_turn(
            session_id=session.id,
            participant_content="The first answer names the archive queue.",
            chip_selected=None,
            repository=repo,
            validator=_PassValidator(),
            router=_StubRouter(),
            cache=RetrievalCache(),
        )
        assert first.agent_turn is not None
        assert first.participant_turn is not None
        await run_post_turn_background(
            session_id=session.id,
            campaign_id=campaign.id,
            participant_turn_id=first.participant_turn.id,
            agent_turn_id=first.agent_turn.id,
            repository=repo,
            router=_StubRouter(),
            validator=_PassValidator(),
            cache=RetrievalCache(),
            bus=bus,
        )

    asyncio.run(main())

    refreshed = repo.get_interview_session(session.id)
    assert refreshed is not None
    assert refreshed.next_plan is None
    planned_envelopes = [
        env for env in bus.replay(campaign.id, since=-1) if env.name == "brain_b_planned"
    ]
    assert planned_envelopes == []


def test_post_turn_background_floors_answered_axis_from_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fast_brain_a(monkeypatch)

    async def zero_scoring_brain_b(**kwargs: Any) -> BrainBIntent:
        return BrainBIntent(
            active_axis="R2",
            axes_coverage=[
                {"axis": "R1", "score": 0.0},
                {"axis": "R2", "score": 0.0},
            ],
            question_intent="Ask about the next axis.",
            get_user_input=GetUserInputOptions(
                question="Where did the handoff break next?",
                options=["During staging", "At the transfer", "Discuss this more."],
                allow_free_text=True,
            ),
            retrieval_used=False,
            retrieval_chunks=[],
        )

    monkeypatch.setattr(interview_loop_module, "run_brain_b_interviewer", zero_scoring_brain_b)

    repo = InMemoryRepository()
    campaign, session = _seed_live_session(repo, axes=["R1 — Workflow", "R2 — Trust"])
    bus = CampaignEventBus()

    async def main() -> None:
        result = await run_interview_turn(
            session_id=session.id,
            participant_content="The archive queue failed before the transfer completed.",
            chip_selected=None,
            repository=repo,
            validator=_PassValidator(),
            router=_StubRouter(),
            cache=RetrievalCache(),
        )
        assert result.agent_turn is not None
        assert result.participant_turn is not None
        await run_post_turn_background(
            session_id=session.id,
            campaign_id=campaign.id,
            participant_turn_id=result.participant_turn.id,
            agent_turn_id=result.agent_turn.id,
            repository=repo,
            router=_StubRouter(),
            validator=_PassValidator(),
            cache=RetrievalCache(),
            bus=bus,
        )

    asyncio.run(main())

    refreshed = repo.get_interview_session(session.id)
    assert refreshed is not None
    assert refreshed.next_plan is not None
    scores = {
        entry.axis: entry.score
        for entry in refreshed.next_plan.axes_coverage
    }
    assert scores["R1"] == pytest.approx(0.20)
    assert scores["R2"] == 0.0


def test_validator_floor_uses_active_axis_when_answered_axis_missing() -> None:
    intent = BrainBIntent(
        active_axis="R2",
        axes_coverage=[
            {"axis": "R1", "score": 0.0},
            {"axis": "R2", "score": 0.0},
        ],
        question_intent="Ask about the next axis.",
        get_user_input=GetUserInputOptions(
            question="Where did the handoff break next?",
            options=["During staging", "At the transfer", "Discuss this more."],
            allow_free_text=True,
        ),
    )
    floored = interview_loop_module._floor_answered_axis_from_validator(
        intent,
        answered_axis_prefix="",
        validation={"coverage_score": 0.8, "quality_score": 0.7},
    )
    scores = {entry.axis: entry.score for entry in floored.axes_coverage}
    assert scores["R1"] == 0.0
    assert scores["R2"] == pytest.approx(0.20)


def test_cold_start_pre_plan_populates_next_plan_before_first_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fast_brain_a(monkeypatch)
    captured: dict[str, Any] = {}

    async def fast_brain_b(**kwargs: Any) -> BrainBIntent:
        captured["transcript_tail"] = kwargs["transcript_tail"]
        captured["participant_context"] = kwargs["participant_context"]
        captured["eligible_question_ids"] = kwargs["eligible_question_ids"]
        captured["enable_tools"] = kwargs["enable_tools"]
        captured["reasoning_budget_tokens"] = kwargs["reasoning_budget_tokens"]
        captured["compact_context"] = kwargs["compact_context"]
        captured["outline_question_ids"] = [
            question.id for question in kwargs["outline"].question_bank
        ]
        return _planned_intent()

    monkeypatch.setattr(interview_loop_module, "run_brain_b_interviewer", fast_brain_b)

    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Cold start harness", min_n=3, max_n=6)
    outline = campaign.outline.model_copy(deep=True)
    outline.axes = ["workflow"]
    outline.question_bank = [
        SurveyQuestion(
            id="operator-q",
            prompt="What broke most recently?",
            applies_to_roles=["Operator"],
        ),
        SurveyQuestion(
            id="scientist-q",
            prompt="What result did you need?",
            applies_to_roles=["Scientist"],
        ),
    ]
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
        micro_form_answers={
            "role_self_description": "Operator",
            "evidence_of_belonging": "I run storage for an HPC facility.",
        },
    )
    bus = CampaignEventBus()

    async def main() -> None:
        await run_pre_plan_background(
            session_id=session.id,
            campaign_id=campaign.id,
            repository=repo,
            router=_StubRouter(),
            cache=RetrievalCache(),
            bus=bus,
        )
        warmed = repo.get_interview_session(session.id)
        assert warmed is not None
        assert warmed.next_plan is not None
        assert warmed.next_plan.active_axis == "planned_axis"

        result = await run_interview_turn(
            session_id=session.id,
            participant_content="The archive queue failed during a beamline run.",
            chip_selected=None,
            repository=repo,
            validator=_PassValidator(),
            router=_StubRouter(),
            cache=RetrievalCache(),
        )
        assert result.agent_turn is not None
        assert result.agent_turn.brain_b_intent is not None
        assert result.agent_turn.brain_b_intent.active_axis == "planned_axis"
        assert result.agent_turn.validation == {"planner_source": "brain_b"}

    asyncio.run(main())

    assert captured["transcript_tail"] == []
    assert captured["participant_context"] == {
        "role_self_description": "Operator",
        "evidence_of_belonging": "I run storage for an HPC facility.",
    }
    assert captured["eligible_question_ids"] == ["operator-q"]
    assert captured["outline_question_ids"] == ["operator-q"]
    assert captured["enable_tools"] is True
    assert captured["reasoning_budget_tokens"] == 1024
    assert captured["compact_context"] is True


def test_late_cold_start_pre_plan_does_not_overwrite_after_first_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fast_brain_a(monkeypatch)

    async def slow_brain_b(**kwargs: Any) -> BrainBIntent:
        await asyncio.sleep(0.05)
        return _planned_intent()

    monkeypatch.setattr(interview_loop_module, "run_brain_b_interviewer", slow_brain_b)

    repo = InMemoryRepository()
    campaign, session = _seed_live_session(repo, axes=["workflow"])
    bus = CampaignEventBus()

    async def main() -> None:
        warmup = asyncio.create_task(
            run_pre_plan_background(
                session_id=session.id,
                campaign_id=campaign.id,
                repository=repo,
                router=_StubRouter(),
                cache=RetrievalCache(),
                bus=bus,
            )
        )
        result = await run_interview_turn(
            session_id=session.id,
            participant_content="The queue failed before the transfer completed.",
            chip_selected=None,
            repository=repo,
            validator=_PassValidator(),
            router=_StubRouter(),
            cache=RetrievalCache(),
        )
        assert result.agent_turn is not None
        assert result.agent_turn.brain_b_intent is not None
        assert result.agent_turn.brain_b_intent.active_axis != "planned_axis"
        assert result.agent_turn.validation == {"planner_source": "scaffold"}
        await asyncio.wait_for(warmup, timeout=1)

    asyncio.run(main())

    refreshed = repo.get_interview_session(session.id)
    assert refreshed is not None
    assert refreshed.next_plan is None
