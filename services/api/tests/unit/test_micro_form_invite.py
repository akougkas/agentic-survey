from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agentic_survey.api.invites as invites_module
from agentic_survey.api.invites import router as invites_router
from agentic_survey.auth import require_admin_session
from agentic_survey.config import get_settings
from agentic_survey.domain.intent import BrainBIntent
from agentic_survey.domain.outline import MicroFormField, OutlineArtifact
from agentic_survey.domain.tools import GetUserInputOptions
from agentic_survey.engine.interview_loop import opening_turn_message
from agentic_survey.engine.state_machine import CampaignState
from agentic_survey.repository import Campaign, InMemoryRepository, get_repository


@pytest.fixture(autouse=True)
def pre_plan_spawns(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    class _StubRouter:
        pass

    def fake_spawn_pre_plan_bg(**kwargs):
        calls.append(kwargs)
        return None

    monkeypatch.setattr(invites_module, "get_litellm_router", lambda: _StubRouter())
    monkeypatch.setattr(invites_module, "spawn_pre_plan_bg", fake_spawn_pre_plan_bg)
    return calls


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


def test_redeem_schedules_cold_start_pre_plan(pre_plan_spawns: list[dict]) -> None:
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

    assert len(pre_plan_spawns) == 1
    call = pre_plan_spawns[0]
    assert call["session_id"] == session_id
    assert call["campaign_id"] == campaign.id
    assert call["repository"] is repo


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
    assert message.startswith("Mira here.")


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
    assert "skip" in fallback_lower and "pause" in fallback_lower


def test_opening_turn_message_names_controls_once() -> None:
    campaign, repo, session_id = _campaign_with_answers(
        {"evidence_of_belonging": "Operating a Slurm cluster."}
    )
    session = repo.get_interview_session(session_id)
    assert session is not None
    message = opening_turn_message(campaign, session)
    controls_sentence = "You can skip, pause, come back later, or stop anytime."
    assert message.count(controls_sentence) == 1


@pytest.mark.parametrize(
    "raw,expected_head",
    [
        ("Storage engineer, HPC, tape", "Storage engineer"),
        ("Run a Slurm cluster for a physics group", "Run a Slurm cluster for a physics"),
        ("  hot-tier reclamation.  ", "hot-tier reclamation"),
    ],
)
def test_noun_phrase_extractor_handles_clauses_and_whitespace(raw: str, expected_head: str) -> None:
    from agentic_survey.engine.interview_loop import _extract_noun_phrase

    head = _extract_noun_phrase(raw)
    assert head.startswith(expected_head) or head == expected_head


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
