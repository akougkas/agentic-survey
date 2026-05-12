from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agentic_survey.llm.callbacks import set_llm_audit_repository, success_callback
from agentic_survey.repository import InMemoryRepository


def test_success_callback_persists_structured_audit_without_raw_content() -> None:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Audit", min_n=3, max_n=6)
    session = repo.start_interview_session(
        campaign_id=campaign.id,
        invite_id=None,
        consent_mode="anonymous",
        identity_label="",
        persona_snapshot={},
        pinned_endpoint="chatter",
    )
    set_llm_audit_repository(repo)
    start = datetime.now(tz=UTC)

    success_callback(
        {
            "model": "mira-chatter",
            "metadata": {
                "surface": "interviewer",
                "brain": "A",
                "campaign_id": campaign.id,
                "session_id": session.id,
                "turn_id": "turn-1",
                "catalog_id": "chatter-default",
                "catalog_role": "chatter",
                "endpoint_name": "chatter",
                "endpoint_model": "local-model",
            },
        },
        {
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            "choices": [{"message": {"content": "visible participant prose"}}],
        },
        start,
        start + timedelta(milliseconds=25),
    )
    set_llm_audit_repository(None)

    rows = repo.list_llm_audits(campaign_id=campaign.id, session_id=session.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.surface == "interviewer"
    assert row.brain == "A"
    assert row.turn_id == "turn-1"
    assert row.prompt_tokens == 11
    assert row.completion_tokens == 7
    assert row.total_tokens == 18
    assert "visible participant prose" not in row.model_dump_json()
