from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentic_survey.api import sessions as sessions_module
from agentic_survey.api.admin import router as admin_router
from agentic_survey.api.invites import router as invites_router
from agentic_survey.api.sessions import router as sessions_router
from agentic_survey.auth import require_admin_session
from agentic_survey.domain.intent import BrainBIntent
from agentic_survey.domain.outline import MicroFormField, OutlineArtifact
from agentic_survey.domain.tools import GetUserInputOptions
from agentic_survey.engine import interview_loop as interview_loop_module
from agentic_survey.engine.event_bus import CampaignEventBus, reset_event_bus
from agentic_survey.engine.interview_loop import run_post_turn_background, run_pre_plan_background
from agentic_survey.engine.retrieval_cache import RetrievalCache
from agentic_survey.engine.state_machine import CampaignState
from agentic_survey.llm import callbacks as callbacks_module
from agentic_survey.repository import InMemoryRepository, get_repository


class _StubRouter:
    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        return {"data": [{"embedding": [0.01] * 768} for _ in input]}

    async def acompletion(self, **kwargs: Any):
        async def _chunks():
            yield {"choices": [{"delta": {"content": "grounded "}}]}
            yield {"choices": [{"delta": {"content": "reply"}}]}

        return _chunks()


class _PassValidator:
    async def validate(self, **_kwargs: Any):
        from agentic_survey.agents.validator import ValidationResult

        return ValidationResult(
            coverage_score=0.7,
            quality_score=0.8,
            follow_up_needed=False,
            is_spam=False,
            extracted_concepts=[{"label": "queue metadata", "type": "workflow"}],
            extracted_relations=[],
        )


def _intent(*, audit_id: str | None = None, active_axis: str = "R1 workflow") -> BrainBIntent:
    return BrainBIntent(
        active_axis=active_axis,
        axes_coverage=[],
        question_intent="Ask about the concrete handoff.",
        get_user_input=GetUserInputOptions(
            question="Which handoff broke?",
            options=["Queue metadata", "Storage tier", "Discuss this more."],
            allow_free_text=True,
        ),
        outline_patch=None,
        ready_for_review=False,
        should_close=False,
        closing=False,
        retrieval_used=audit_id is not None,
        retrieval_chunks=["chunk-1"] if audit_id else [],
        retrieval_audit_ids=[audit_id] if audit_id else [],
    )


def test_full_local_interview_pipeline_observability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_event_bus()
    repo = InMemoryRepository()
    outline = OutlineArtifact(
        axes=["R1 workflow", "R3 handoff"],
        consent_language="Participants choose attribution.",
        micro_form_schema=[
            MicroFormField(
                key="evidence_of_belonging",
                label="What do you work on?",
                field_type="long_text",
                required=True,
            )
        ],
    )
    campaign = repo.create_campaign(
        title="Pipeline",
        min_n=3,
        max_n=6,
        outline=outline,
        source="seed",
        state=CampaignState.LIVE,
    )
    source = repo.create_knowledge_source(
        campaign_id=campaign.id,
        kind="raw_text",
        title="Approved operator note",
        hash_value="approved-note",
        status="approved",
    )
    chunk = repo.create_knowledge_chunk(
        campaign_id=campaign.id,
        source_id=source.id,
        content="Approved note about queue metadata handoffs.",
        position=0,
        char_start=0,
        char_end=44,
        approved=True,
    )
    audit = repo.record_retrieval_audit(
        campaign_id=campaign.id,
        surface="interviewer",
        query="queue metadata handoff",
        top_k=1,
        chunk_ids=[chunk.id],
        scores=[0.9],
        mode="bm25",
        cache_hit=False,
    )
    invite = repo.create_invite(campaign.id, label="operator")

    preplan_spawns: list[dict[str, Any]] = []
    post_turn_spawns: list[dict[str, Any]] = []
    monkeypatch.setattr(sessions_module, "get_litellm_router", lambda: _StubRouter())
    monkeypatch.setattr(
        "agentic_survey.api.invites.get_litellm_router",
        lambda: _StubRouter(),
    )
    monkeypatch.setattr(
        "agentic_survey.api.invites.spawn_pre_plan_bg",
        lambda **kwargs: preplan_spawns.append(kwargs),
    )
    monkeypatch.setattr(
        sessions_module,
        "spawn_post_turn_bg",
        lambda **kwargs: post_turn_spawns.append(kwargs),
    )
    monkeypatch.setattr(callbacks_module, "_audit_repository", repo)

    app = FastAPI()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.include_router(invites_router, prefix="/api")
    app.include_router(sessions_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")
    client = TestClient(app)

    redeem = client.post(
        f"/api/invites/{invite.token}/redeem",
        json={
            "consent_mode": "anonymous",
            "micro_form_answers": {
                "evidence_of_belonging": "I run storage queues for a facility.",
            },
        },
    )
    assert redeem.status_code == 200
    session_id = redeem.json()["session"]["id"]
    assert preplan_spawns

    async def fake_preplan_brain_b(**_kwargs: Any) -> BrainBIntent:
        return _intent(audit_id=audit.id)

    monkeypatch.setattr(interview_loop_module, "run_brain_b_interviewer", fake_preplan_brain_b)
    assert repo.try_acquire_preplan_lock(session_id)
    asyncio.run(
        run_pre_plan_background(
            session_id=session_id,
            campaign_id=campaign.id,
            repository=repo,
            router=_StubRouter(),
            cache=RetrievalCache(),
            bus=CampaignEventBus(),
        )
    )

    start = client.post(f"/api/sessions/{session_id}/start")
    assert start.status_code == 200

    turn = client.post(
        f"/api/sessions/{session_id}/turns",
        json={"content": "The queue metadata vanished between scheduling and storage."},
    )
    assert turn.status_code == 200
    agent_turn = turn.json()["session"]["turns"][-1]
    participant_turn = turn.json()["session"]["turns"][-2]
    assert agent_turn["content"] == "grounded reply"
    assert agent_turn["retrieval_audit_id"] == audit.id
    assert post_turn_spawns

    async def fake_post_brain_b(**_kwargs: Any) -> BrainBIntent:
        return _intent(active_axis="R3 handoff")

    monkeypatch.setattr(interview_loop_module, "run_brain_b_interviewer", fake_post_brain_b)
    asyncio.run(
        run_post_turn_background(
            session_id=session_id,
            campaign_id=campaign.id,
            participant_turn_id=participant_turn["id"],
            agent_turn_id=agent_turn["id"],
            repository=repo,
            router=_StubRouter(),
            validator=_PassValidator(),
            cache=RetrievalCache(),
            bus=CampaignEventBus(),
        )
    )

    events = client.get(f"/api/admin/campaigns/{campaign.id}/events")
    assert events.status_code == 200
    event_names = [row["event_name"] for row in events.json()["items"]]
    for expected in {
        "session_created",
        "preplan_ready",
        "brain_b_planned",
        "session_started",
        "participant_turn",
        "turn_complete",
        "validator_scored",
        "graph_delta",
        "concepts_extracted",
    }:
        assert expected in event_names

    llm = client.get(f"/api/admin/campaigns/{campaign.id}/sessions/{session_id}/llm-audits")
    assert llm.status_code == 200
    assert any(row["brain"] == "A" for row in llm.json()["items"])

    audit_response = client.get(
        f"/api/admin/campaigns/{campaign.id}/sessions/{session_id}/turns/{agent_turn['id']}/audit"
    )
    assert audit_response.status_code == 200
    audit_body = audit_response.json()
    assert audit_body["retrieval"]["retrieval_audit_id"] == audit.id
    assert audit_body["retrieval"]["audits"][0]["chunks"][0]["id"] == chunk.id
    assert repo.get_validator_result(participant_turn["id"]) is not None
    assert repo.list_graph_edges_for_campaign(campaign.id) == []
    assert repo.list_concepts_for_campaign(campaign.id)[0].label == "queue metadata"
