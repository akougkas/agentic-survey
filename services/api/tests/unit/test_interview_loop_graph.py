from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

import pytest

from agentic_survey.agents.validator import ValidationResult
from agentic_survey.domain.intent import BrainBIntent
from agentic_survey.domain.tools import GetUserInputOptions
from agentic_survey.engine import interview_loop as interview_loop_module
from agentic_survey.engine.interview_loop import run_interview_turn
from agentic_survey.engine.retrieval_cache import RetrievalCache
from agentic_survey.repository import InMemoryRepository


class _StubRouter:
    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        return {"data": [{"embedding": [0.01] * 768} for _ in input]}

    async def acompletion(self, **kwargs: Any):
        # Closing path streams tokens; yield a benign short reply.
        async def _chunks():
            yield {"choices": [{"delta": {"content": "Thanks."}}]}

        return _chunks()


class _FakeValidator:
    def __init__(self, concepts: list[dict], relations: list[dict] | None = None) -> None:
        self._concepts = concepts
        self._relations = relations or []

    async def validate(
        self,
        *,
        campaign,
        content: str,
        outline,
        previous_agent_question: str,
    ) -> ValidationResult:
        return ValidationResult(
            coverage_score=0.6,
            quality_score=0.5,
            follow_up_needed=False,
            follow_up_reason="",
            is_spam=False,
            extracted_concepts=list(self._concepts),
            extracted_relations=list(self._relations),
        )


def _fake_brain_b_intent() -> BrainBIntent:
    return BrainBIntent(
        active_axis="concrete_moments",
        axes_coverage=[],
        question_intent="deepen",
        get_user_input=GetUserInputOptions(
            question="What else changed after that?",
            options=["Kept the process", "Adjusted the process", "Discuss this more."],
            allow_free_text=True,
        ),
        outline_patch=None,
        ready_for_review=False,
        should_close=False,
        closing=False,
        retrieval_used=False,
        retrieval_chunks=[],
    )


def _install_fake_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_brain_b(**kwargs: Any) -> BrainBIntent:
        return _fake_brain_b_intent()

    async def fake_stream(**kwargs: Any) -> AsyncIterator[str]:
        for token in ("Hel", "lo", "."):
            yield token

    def _stream_factory(**kwargs: Any) -> AsyncIterator[str]:
        return fake_stream(**kwargs)

    monkeypatch.setattr(
        interview_loop_module, "run_brain_b_interviewer", fake_brain_b
    )
    monkeypatch.setattr(
        interview_loop_module, "stream_brain_a", _stream_factory
    )


def _seed_live_session(repo: InMemoryRepository):
    campaign = repo.create_campaign(title="Graph wiring", min_n=3, max_n=6)
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
        content="Tell me about the last time this came up.",
    )
    return campaign, session


def test_non_control_turn_emits_one_graph_delta_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_agents(monkeypatch)
    repo = InMemoryRepository()
    campaign, session = _seed_live_session(repo)
    validator = _FakeValidator(
        concepts=[
            {"label": "code review", "type": "process"},
            {"label": "feedback", "type": "signal"},
        ],
        relations=[],
    )

    result = asyncio.run(
        run_interview_turn(
            session_id=session.id,
            participant_content="We use code review to build feedback loops.",
            chip_selected=None,
            repository=repo,
            validator=validator,
            router=_StubRouter(),
            cache=RetrievalCache(),
        )
    )

    graph_events = [event for event in result.events if event.name == "graph_delta"]
    assert len(graph_events) == 1
    payload = graph_events[0].data
    assert len(payload["add_nodes"]) == 2
    assert all(node["is_new"] is True for node in payload["add_nodes"])
    assert len(payload["add_edges"]) == 1


@pytest.mark.parametrize("control", ["pause", "skip", "continue", "stop"])
def test_control_signal_turn_emits_no_graph_delta(
    monkeypatch: pytest.MonkeyPatch, control: str
) -> None:
    _install_fake_agents(monkeypatch)
    repo = InMemoryRepository()
    campaign, session = _seed_live_session(repo)
    # The validator must not be called for control signals, so a stub that
    # raises on .validate() also proves the invariant.
    class _Raising:
        async def validate(self, **kwargs: Any) -> ValidationResult:
            raise AssertionError("validator must not run for control signals")

    result = asyncio.run(
        run_interview_turn(
            session_id=session.id,
            participant_content=control,
            chip_selected=None,
            repository=repo,
            validator=_Raising(),
            router=_StubRouter(),
            cache=RetrievalCache(),
        )
    )

    graph_events = [event for event in result.events if event.name == "graph_delta"]
    assert graph_events == []


def test_empty_concepts_still_emits_graph_delta_with_empty_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_agents(monkeypatch)
    repo = InMemoryRepository()
    campaign, session = _seed_live_session(repo)
    validator = _FakeValidator(concepts=[], relations=[])

    result = asyncio.run(
        run_interview_turn(
            session_id=session.id,
            participant_content="A normal answer with no tagged concepts.",
            chip_selected=None,
            repository=repo,
            validator=validator,
            router=_StubRouter(),
            cache=RetrievalCache(),
        )
    )

    graph_events = [event for event in result.events if event.name == "graph_delta"]
    assert len(graph_events) == 1
    payload = graph_events[0].data
    assert payload["add_nodes"] == []
    assert payload["add_edges"] == []
    assert payload["light_up"] == []
