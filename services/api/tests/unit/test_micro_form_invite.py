from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentic_survey.api import invites as invites_module
from agentic_survey.api import sessions as sessions_module
from agentic_survey.api.invites import router as invites_router
from agentic_survey.api.sessions import router as sessions_router
from agentic_survey.auth import require_admin_session
from agentic_survey.config import get_settings
from agentic_survey.domain.intent import BrainBIntent
from agentic_survey.domain.outline import MicroFormField, OutlineArtifact
from agentic_survey.domain.tools import GetUserInputOptions
from agentic_survey.engine import interview_loop as interview_loop_module
from agentic_survey.engine.interview_loop import opening_turn_message
from agentic_survey.engine.state_machine import CampaignState
from agentic_survey.repository import Campaign, InMemoryRepository, get_repository


@pytest.fixture(autouse=True)
def pre_plan_spawns(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_spawn_pre_plan_bg(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(invites_module, "spawn_pre_plan_bg", fake_spawn_pre_plan_bg)
    monkeypatch.setattr(invites_module, "get_litellm_router", lambda: object())
    return calls


def _planned_intent() -> BrainBIntent:
    return BrainBIntent(
        active_axis="planned_axis",
        question_intent="Ask the ready pre-plan probe.",
        get_user_input=GetUserInputOptions(
            question="What happened next?",
            options=["The queue failed", "The handoff failed", "Discuss this more."],
            allow_free_text=True,
        ),
        axes_coverage=[],
        retrieval_used=False,
        retrieval_chunks=[],
        should_close=False,
    )


def test_micro_form_field_round_trips_options() -> None:
    field = MicroFormField(
        key="role_self_description",
        label="Which one fits best?",
        field_type="single_select",
        required=False,
        options=["Scientist", "Operator", "Other"],
    )
    restored = MicroFormField.model_validate(field.model_dump())
    assert restored == field
    assert restored.options == ["Scientist", "Operator", "Other"]


def test_micro_form_field_options_default_empty() -> None:
    field = MicroFormField(key="k", label="l")
    assert field.options == []


def _build_invite_app() -> tuple[FastAPI, InMemoryRepository, Campaign, str]:
    repo = InMemoryRepository()
    outline = OutlineArtifact(
        consent_language="Participant chooses anonymous or named.",
        micro_form_schema=[
            MicroFormField(
                key="evidence_of_belonging",
                label="What do you work on with scientific or research data?",
                field_type="long_text",
                required=True,
            ),
            MicroFormField(
                key="role_self_description",
                label="Pick the closest match.",
                field_type="single_select",
                required=False,
                options=["Operator", "Scientist", "Builder"],
            ),
        ],
    )
    campaign = repo.create_campaign(
        title="Pulse",
        min_n=3,
        max_n=10,
        outline=outline,
        source="seed",
        state=CampaignState.LIVE,
    )
    invite = repo.create_invite(campaign.id, label="test")
    app = FastAPI()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.dependency_overrides[get_settings] = get_settings
    app.include_router(invites_router, prefix="/api")
    return app, repo, campaign, invite.token


def test_redeem_rejects_missing_required_micro_form_field() -> None:
    app, _repo, _campaign, token = _build_invite_app()
    client = TestClient(app)
    response = client.post(
        f"/api/invites/{token}/redeem",
        json={"consent_mode": "anonymous", "micro_form_answers": {}},
    )
    assert response.status_code == 422
    assert "evidence_of_belonging" in response.json()["detail"]


def test_redeem_rejects_single_select_value_not_in_options() -> None:
    app, _repo, _campaign, token = _build_invite_app()
    client = TestClient(app)
    response = client.post(
        f"/api/invites/{token}/redeem",
        json={
            "consent_mode": "anonymous",
            "micro_form_answers": {
                "evidence_of_belonging": "I run storage for an HPC facility.",
                "role_self_description": "Not a real option",
            },
        },
    )
    assert response.status_code == 422
    assert "role_self_description" in response.json()["detail"]


def test_redeem_persists_micro_form_answers_on_session() -> None:
    app, repo, campaign, token = _build_invite_app()
    client = TestClient(app)
    response = client.post(
        f"/api/invites/{token}/redeem",
        json={
            "consent_mode": "anonymous",
            "micro_form_answers": {
                "evidence_of_belonging": "I run storage at a university HPC facility.",
                "role_self_description": "Operator",
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    session_id = body["session"]["id"]
    stored = repo.get_interview_session(session_id)
    assert stored is not None
    assert stored.micro_form_answers == {
        "evidence_of_belonging": "I run storage at a university HPC facility.",
        "role_self_description": "Operator",
    }
    assert stored.campaign_id == campaign.id


def test_redeem_schedules_cold_start_pre_plan(pre_plan_spawns: list[dict[str, Any]]) -> None:
    app, repo, campaign, token = _build_invite_app()
    client = TestClient(app)
    response = client.post(
        f"/api/invites/{token}/redeem",
        json={
            "consent_mode": "anonymous",
            "micro_form_answers": {
                "evidence_of_belonging": "I run storage at a university HPC facility.",
                "role_self_description": "Operator",
            },
        },
    )
    assert response.status_code == 200
    session_id = response.json()["session"]["id"]
    assert response.json()["session"]["campaign_id"] == campaign.id
    assert len(pre_plan_spawns) == 1
    assert pre_plan_spawns[0]["session_id"] == session_id
    assert pre_plan_spawns[0]["campaign_id"] == campaign.id
    assert pre_plan_spawns[0]["repository"] is repo


def test_ready_redeem_preplan_does_not_drive_first_substantive_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, repo, campaign, token = _build_invite_app()
    app.include_router(sessions_router, prefix="/api")

    def warm_spawn_pre_plan_bg(**kwargs: Any) -> None:
        repository = kwargs["repository"]
        session_id = kwargs["session_id"]
        if repository.try_acquire_preplan_lock(session_id):
            repository.update_next_plan(session_id, _planned_intent())
            repository.update_preplan_status(session_id, status="ready")

    async def fake_stream_brain_a(**_kwargs: Any) -> AsyncIterator[str]:
        yield "ready "
        yield "plan"

    def fake_stream_factory(**kwargs: Any) -> AsyncIterator[str]:
        return fake_stream_brain_a(**kwargs)

    async def fresh_brain_b(**kwargs: Any) -> BrainBIntent:
        return _planned_intent().model_copy(update={"active_axis": "fresh_axis"})

    post_turn_spawns: list[dict[str, Any]] = []
    monkeypatch.setattr(invites_module, "spawn_pre_plan_bg", warm_spawn_pre_plan_bg)
    monkeypatch.setattr(sessions_module, "get_litellm_router", lambda: object())
    monkeypatch.setattr(sessions_module, "spawn_post_turn_bg", lambda **kwargs: post_turn_spawns.append(kwargs))
    monkeypatch.setattr(interview_loop_module, "stream_brain_a", fake_stream_factory)
    monkeypatch.setattr(interview_loop_module, "run_brain_b_interviewer", fresh_brain_b)

    client = TestClient(app)
    redeem = client.post(
        f"/api/invites/{token}/redeem",
        json={
            "consent_mode": "anonymous",
            "micro_form_answers": {
                "evidence_of_belonging": "I run storage at a university HPC facility.",
                "role_self_description": "Operator",
            },
        },
    )
    assert redeem.status_code == 200
    session_id = redeem.json()["session"]["id"]

    start = client.post(f"/api/sessions/{session_id}/start")
    assert start.status_code == 200

    turn = client.post(
        f"/api/sessions/{session_id}/turns",
        json={"content": "The archive queue failed during a beamline run."},
    )
    assert turn.status_code == 200
    turns = turn.json()["session"]["turns"]
    agent_turn = turns[-1]
    assert agent_turn["role"] == "agent"
    assert agent_turn["content"] == "ready plan"
    assert agent_turn["validation"] == {"planner_source": "brain_b"}
    assert agent_turn["brain_b_intent"]["active_axis"] == "fresh_axis"
    assert post_turn_spawns


def _campaign_with_answers(answers: dict[str, str]) -> tuple[Campaign, InMemoryRepository, str]:
    repo = InMemoryRepository()
    outline = OutlineArtifact(
        consent_language="ok",
        micro_form_schema=[
            MicroFormField(
                key="evidence_of_belonging",
                label="tell us",
                field_type="long_text",
                required=True,
            ),
        ],
    )
    campaign = repo.create_campaign(
        title="CITADEL Community Pulse: validating agentic lifecycle assistance",
        min_n=3,
        max_n=10,
        outline=outline,
        source="seed",
        state=CampaignState.LIVE,
    )
    invite = repo.create_invite(campaign.id, label="opener")
    session = repo.start_interview_session(
        campaign_id=campaign.id,
        invite_id=invite.id,
        consent_mode="anonymous",
        identity_label="",
        persona_snapshot=dict(outline.persona_hints),
        pinned_endpoint="mini",
        micro_form_answers=answers,
    )
    return campaign, repo, session.id


def test_opening_turn_message_echoes_noun_phrase_when_evidence_present() -> None:
    campaign, repo, session_id = _campaign_with_answers(
        {
            "evidence_of_belonging": "I run storage at a university HPC facility, 12 PB across NVMe, tape, and spinning disk.",
        }
    )
    session = repo.get_interview_session(session_id)
    assert session is not None
    message = opening_turn_message(campaign, session)
    assert "storage" in message.lower() or "hpc" in message.lower()
    assert message.startswith("Welcome. I'm Mira")


def test_opening_turn_message_forbidden_substrings_absent_in_both_branches() -> None:
    # Title explicitly contains the forbidden term; the new opener must not quote it.
    forbidden = ["agentic", "autonomous", " AI "]

    campaign, repo, session_id = _campaign_with_answers(
        {"evidence_of_belonging": "I build ML training pipelines."}
    )
    session = repo.get_interview_session(session_id)
    assert session is not None
    message = opening_turn_message(campaign, session)
    lower = message.lower()
    for bad in forbidden:
        assert bad.lower() not in lower, f"opener leaked {bad!r}: {message}"

    campaign2, repo2, session_id2 = _campaign_with_answers({})
    session2 = repo2.get_interview_session(session_id2)
    assert session2 is not None
    fallback = opening_turn_message(campaign2, session2)
    fallback_lower = fallback.lower()
    for bad in forbidden:
        assert bad.lower() not in fallback_lower, f"fallback leaked {bad!r}: {fallback}"
    assert "what kind of work" in fallback_lower


def test_opening_turn_message_leaves_controls_to_ui() -> None:
    campaign, repo, session_id = _campaign_with_answers(
        {"evidence_of_belonging": "Operating a Slurm cluster."}
    )
    session = repo.get_interview_session(session_id)
    assert session is not None
    message = opening_turn_message(campaign, session)
    lower = message.lower()
    for phrase in ("skip", "pause", "come back", "stop anytime"):
        assert phrase not in lower


def test_opening_turn_message_has_two_beats_and_under_word_budget() -> None:
    """Greeting + consent posture + soft opener; under 70 words; ends with one '?'.

    Beat-1 marker: starts with the greeting.
    Beat-2 marker: ends with a single question and includes the soft-opener cue.
    """
    campaign, repo, session_id = _campaign_with_answers(
        {"evidence_of_belonging": "I run cryo-EM single-particle reconstruction on a university cluster."}
    )
    session = repo.get_interview_session(session_id)
    assert session is not None
    message = opening_turn_message(campaign, session)
    word_count = len(message.split())
    assert word_count <= 70, f"opener exceeded 70 words: {word_count} -> {message}"
    assert message.startswith("Welcome. I'm Mira")
    assert "anonymous" in message.lower()
    assert "To start:" in message
    assert message.count("?") == 1, f"opener must end with one question: {message!r}"


def test_opening_turn_message_does_not_fabricate_role_when_unset() -> None:
    """Named-no-role redemption asks the role question rather than guessing."""
    repo = InMemoryRepository()
    outline = OutlineArtifact(
        consent_language="ok",
        micro_form_schema=[
            MicroFormField(
                key="evidence_of_belonging",
                label="tell us",
                field_type="long_text",
                required=True,
            ),
        ],
    )
    campaign = repo.create_campaign(
        title="CITADEL Community Pulse",
        min_n=3,
        max_n=10,
        outline=outline,
        source="seed",
        state=CampaignState.LIVE,
    )
    invite = repo.create_invite(campaign.id, label="opener")
    session = repo.start_interview_session(
        campaign_id=campaign.id,
        invite_id=invite.id,
        consent_mode="named",
        identity_label="A. Researcher",
        persona_snapshot=dict(outline.persona_hints),
        pinned_endpoint="mini",
        micro_form_answers={},
    )
    refreshed = repo.get_interview_session(session.id)
    assert refreshed is not None
    message = opening_turn_message(campaign, refreshed)
    # No role guess and no evidence to echo: the opener must invite a soft
    # self-description rather than name a role for them.
    assert "scientists like you" not in message
    assert "operators like you" not in message
    assert "what kind of work" in message.lower()
    # Named consent must not produce the anonymous phrasing.
    assert "stay anonymous" not in message.lower()


def test_opening_turn_message_uses_role_phrase_when_role_picked() -> None:
    campaign, repo, session_id = _campaign_with_answers(
        {
            "evidence_of_belonging": "I run cryo-EM single-particle reconstruction on a university cluster.",
            "role_self_description": "Research scientist or engineer generating or analyzing data",
        }
    )
    session = repo.get_interview_session(session_id)
    assert session is not None
    message = opening_turn_message(campaign, session)
    assert "scientists like you" in message


@pytest.mark.parametrize(
    "raw,expected_head",
    [
        # Sentence-initial capitalization is dropped because the opener
        # embeds the phrase mid-sentence ("You mentioned <phrase>"); proper
        # nouns like ``Slurm`` keep their casing because the pivot is a
        # whole-word regex, not a global lowercase.
        ("Storage engineer, HPC, tape", "storage engineer"),
        ("Run a Slurm cluster for a physics group", "run a Slurm cluster for a physics"),
        ("  hot-tier reclamation.  ", "hot-tier reclamation"),
    ],
)
def test_noun_phrase_extractor_handles_clauses_and_whitespace(raw: str, expected_head: str) -> None:
    from agentic_survey.engine.interview_loop import _extract_noun_phrase

    head = _extract_noun_phrase(raw)
    assert head.startswith(expected_head) or head == expected_head


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Bare "I" → "You" (capitalized, not all-caps); proper nouns kept.
        ("I run cryo-EM on a Slurm cluster", "You run cryo-EM on a Slurm cluster"),
        ("We operate a tape archive", "Your team operate a tape archive"),
        ("My team supports BIDS workflows", "Your team supports BIDS workflows"),
        # No first-person tokens: pass through unchanged.
        ("Storage engineer, HPC, tape", "Storage engineer, HPC, tape"),
        ("I'm a research software engineer", "You're a research software engineer"),
    ],
)
def test_pivot_to_second_person_preserves_casing_of_proper_nouns(raw: str, expected: str) -> None:
    from agentic_survey.engine.interview_loop import _pivot_to_second_person

    assert _pivot_to_second_person(raw) == expected


def test_opening_turn_message_quotes_in_second_person_when_evidence_is_first_person() -> None:
    campaign, repo, session_id = _campaign_with_answers(
        {
            "evidence_of_belonging": "I run cryo-EM single-particle reconstruction on a university cluster.",
        }
    )
    session = repo.get_interview_session(session_id)
    assert session is not None
    message = opening_turn_message(campaign, session)
    # The participant's first-person self-description must be pivoted; the
    # raw "I run …" string would make Mira sound like she did the work.
    assert "You mentioned I run" not in message
    assert "you run cryo-EM" in message
    # Proper-noun casing (Slurm, BIDS, etc.) is preserved by the pivot's
    # whole-word regex; that survives the opener template too.
    assert "cryo-EM" in message


def test_opening_turn_message_handles_i_am_evidence_without_broken_grammar() -> None:
    campaign, repo, session_id = _campaign_with_answers(
        {
            "evidence_of_belonging": (
                "I am a professor researching data management at scale. "
                "HPC and AI are my main domains, especially storage and I/O."
            ),
            "role_self_description": "Research scientist or engineer generating or analyzing data",
        }
    )
    session = repo.get_interview_session(session_id)
    assert session is not None
    message = opening_turn_message(campaign, session)

    assert "you am" not in message.lower()
    assert "you're a professor researching data management at scale" in message
    assert message.count("?") == 1


def test_update_next_plan_round_trips_brain_b_intent() -> None:
    _campaign, repo, session_id = _campaign_with_answers(
        {"evidence_of_belonging": "I run a Slurm cluster for a physics group."}
    )
    intent = BrainBIntent(
        active_axis="workflow",
        question_intent="Elicit the last concrete job they ran",
        get_user_input=GetUserInputOptions(
            question="What did you run last?",
            options=[
                "A quick experiment",
                "A long campaign",
                "Something else",
                "Discuss this more.",
            ],
            allow_free_text=True,
        ),
        axes_coverage=[],
        retrieval_used=False,
        retrieval_chunks=[],
        should_close=False,
    )
    updated = repo.update_next_plan(session_id, intent)
    assert updated.next_plan is not None
    assert updated.next_plan.model_dump() == intent.model_dump()

    cleared = repo.update_next_plan(session_id, None)
    assert cleared.next_plan is None
