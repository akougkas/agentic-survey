"""Knowledge-source lifecycle, embedding persistence, and retrieval audit.

Covers the gotchas the live smoke caught during M2 and M4:
- ``update_knowledge_source_status`` preserves ``error_detail`` across
  intermediate status bumps (gotcha #23); passing ``""`` clears it.
- ``update_knowledge_chunk_embedding`` round-trips 768-dim floats even
  though the ``KnowledgeChunk`` Pydantic model does not carry the vector
  (gotcha #22).
- ``record_retrieval_audit`` + ``get_retrieval_audit`` preserve record
  IDs, and ``append_interview_turn`` links the audit back to a turn.
"""

from __future__ import annotations

from agentic_survey.db.surreal_repository import SurrealRepository
from agentic_survey.engine.interview_loop import InterviewEvent


def test_error_detail_preserved_across_intermediate_status_bumps(
    surreal_repository: SurrealRepository,
) -> None:
    campaign = surreal_repository.create_campaign(
        title="ErrorDetailFlow", min_n=1, max_n=3
    )
    source = surreal_repository.create_knowledge_source(
        campaign_id=campaign.id,
        kind="url",
        title="flaky",
        hash_value="hash-flaky",
        url="https://example.test/flaky",
        status="queued",
    )

    tier1 = surreal_repository.update_knowledge_source_status(
        source.id,
        status="fetching",
        error_detail="tier1 insufficient",
    )
    assert tier1.error_detail == "tier1 insufficient"

    # Intermediate bumps omit error_detail → prior note survives.
    extracting = surreal_repository.update_knowledge_source_status(
        source.id, status="extracting"
    )
    assert extracting.error_detail == "tier1 insufficient"
    chunking = surreal_repository.update_knowledge_source_status(
        source.id, status="chunking"
    )
    assert chunking.error_detail == "tier1 insufficient"

    # Reaching pending_approval clears the note explicitly.
    pending = surreal_repository.update_knowledge_source_status(
        source.id, status="pending_approval", error_detail=""
    )
    assert pending.error_detail is None


def test_update_knowledge_chunk_embedding_round_trip(
    surreal_repository: SurrealRepository,
) -> None:
    campaign = surreal_repository.create_campaign(
        title="EmbeddingRoundTrip", min_n=1, max_n=3
    )
    source = surreal_repository.create_knowledge_source(
        campaign_id=campaign.id,
        kind="raw_text",
        title="seed",
        hash_value="hash-round",
        status="approved",
    )
    chunk = surreal_repository.create_knowledge_chunk(
        campaign_id=campaign.id,
        source_id=source.id,
        content="lorem",
        position=0,
        char_start=0,
        char_end=5,
        approved=True,
    )

    vector = [(i % 7) * 0.01 for i in range(768)]
    surreal_repository.update_knowledge_chunk_embedding(chunk.id, vector)

    rows = surreal_repository._query(
        "SELECT embedding FROM type::thing('knowledge_chunk', $cid);",
        {"cid": chunk.id},
    )
    assert rows, "chunk readback returned no rows"
    stored = rows[0].get("embedding") if isinstance(rows[0], dict) else None
    assert stored is not None, f"no embedding field on row: {rows[0]}"
    assert len(stored) == 768
    # Floats round-trip within machine precision.
    assert [round(v, 6) for v in stored[:10]] == [round(v, 6) for v in vector[:10]]


def test_record_and_get_retrieval_audit(
    surreal_repository: SurrealRepository,
) -> None:
    campaign = surreal_repository.create_campaign(
        title="AuditRoundTrip", min_n=1, max_n=3
    )
    source = surreal_repository.create_knowledge_source(
        campaign_id=campaign.id,
        kind="raw_text",
        title="seed",
        hash_value="hash-audit",
        status="approved",
    )
    chunk = surreal_repository.create_knowledge_chunk(
        campaign_id=campaign.id,
        source_id=source.id,
        content="quotable",
        position=0,
        char_start=0,
        char_end=8,
        approved=True,
    )

    audit = surreal_repository.record_retrieval_audit(
        campaign_id=campaign.id,
        surface="designer",
        query="sampling frame",
        top_k=3,
        chunk_ids=[chunk.id],
        scores=[0.42],
        mode="hybrid",
        cache_hit=False,
    )
    loaded = surreal_repository.get_retrieval_audit(audit.id)
    assert loaded is not None
    assert loaded.id == audit.id
    assert loaded.campaign_id == campaign.id
    assert loaded.surface == "designer"
    assert loaded.query == "sampling frame"
    assert loaded.top_k == 3
    assert loaded.chunk_ids == [chunk.id]
    assert loaded.scores == [0.42]
    assert loaded.mode == "hybrid"
    assert loaded.cache_hit is False


def test_append_interview_turn_links_retrieval_audit(
    surreal_repository: SurrealRepository,
) -> None:
    campaign = surreal_repository.create_campaign(
        title="TurnAuditLink", min_n=1, max_n=3
    )
    source = surreal_repository.create_knowledge_source(
        campaign_id=campaign.id,
        kind="raw_text",
        title="seed",
        hash_value="hash-turn-audit",
        status="approved",
    )
    chunk = surreal_repository.create_knowledge_chunk(
        campaign_id=campaign.id,
        source_id=source.id,
        content="contextual",
        position=0,
        char_start=0,
        char_end=10,
        approved=True,
    )
    audit = surreal_repository.record_retrieval_audit(
        campaign_id=campaign.id,
        surface="interviewer",
        query="context question",
        top_k=1,
        chunk_ids=[chunk.id],
        scores=[0.1],
        mode="bm25",
        cache_hit=True,
    )

    session = surreal_repository.start_interview_session(
        campaign_id=campaign.id,
        invite_id=None,
        consent_mode="anonymous",
        identity_label="anon",
        persona_snapshot={"role": "tester"},
        pinned_endpoint="mini",
    )
    turn = surreal_repository.append_interview_turn(
        session.id,
        role="agent",
        content="Let's clarify the sampling frame.",
        retrieval_audit_id=audit.id,
    )
    assert turn.retrieval_audit_id == audit.id

    rehydrated = surreal_repository.get_interview_session(session.id)
    assert rehydrated is not None
    stored_turn = next((t for t in rehydrated.turns if t.id == turn.id), None)
    assert stored_turn is not None, (
        f"turn {turn.id!r} missing from rehydrated session: "
        f"{[(t.id, t.retrieval_audit_id) for t in rehydrated.turns]!r}"
    )
    # Surreal stores the link as a ``record<retrieval_audit>`` pointer;
    # the row mapper normalizes it back to the bare hex id string so the
    # Python API stays stable for downstream callers.
    assert stored_turn.retrieval_audit_id == audit.id


def test_validator_result_round_trips_by_turn(
    surreal_repository: SurrealRepository,
) -> None:
    campaign = surreal_repository.create_campaign(
        title="ValidatorResultRoundTrip", min_n=1, max_n=3
    )
    session = surreal_repository.start_interview_session(
        campaign_id=campaign.id,
        invite_id=None,
        consent_mode="anonymous",
        identity_label="anon",
        persona_snapshot={"role": "tester"},
        pinned_endpoint="mini",
    )
    turn = surreal_repository.append_interview_turn(
        session.id,
        role="participant",
        content="The archive queue failed during staging.",
    )

    created = surreal_repository.upsert_validator_result(
        turn_id=turn.id,
        validation={
            "coverage_score": 0.4,
            "quality_score": 0.5,
            "follow_up_needed": True,
            "follow_up_reason": "needs a specific handoff",
            "is_spam": False,
            "extracted_concepts": [{"label": "archive queue", "type": "tool"}],
            "extracted_relations": [{"source": "archive queue", "target": "staging"}],
            "objective_tags": ["R1"],
        },
    )
    updated = surreal_repository.upsert_validator_result(
        turn_id=turn.id,
        validation={
            "coverage_score": 0.8,
            "quality_score": 0.7,
            "follow_up_needed": False,
            "follow_up_reason": "",
            "is_spam": False,
            "extracted_concepts": [],
            "extracted_relations": [],
            "objective_tags": ["R1", "R3"],
        },
    )
    loaded = surreal_repository.get_validator_result(turn.id)

    assert loaded is not None
    assert updated.id == created.id
    assert loaded.id == created.id
    assert loaded.turn_id == turn.id
    assert loaded.coverage_score == 0.8
    assert loaded.objective_tags == ["R1", "R3"]


def test_interview_event_round_trips_by_campaign_and_session(
    surreal_repository: SurrealRepository,
) -> None:
    campaign = surreal_repository.create_campaign(
        title="InterviewEventRoundTrip", min_n=1, max_n=3
    )
    session = surreal_repository.start_interview_session(
        campaign_id=campaign.id,
        invite_id=None,
        consent_mode="anonymous",
        identity_label="anon",
        persona_snapshot={"role": "tester"},
        pinned_endpoint="chatter",
    )
    surreal_repository.record_interview_events(
        campaign_id=campaign.id,
        events=[
            InterviewEvent(name="session_started", data={"session_id": session.id}),
            InterviewEvent(name="turn_complete", data={"session_id": session.id, "turn_id": "turn-x"}),
        ],
    )

    campaign_rows = surreal_repository.list_interview_events_for_campaign(campaign.id)
    session_rows = surreal_repository.list_interview_events_for_session(session.id)

    assert [row.sequence for row in campaign_rows] == [0, 1]
    assert [row.event_name for row in session_rows] == ["session_started", "turn_complete"]
    assert session_rows[1].turn_id == "turn-x"
    assert surreal_repository.latest_interview_event_sequence(campaign.id) == 1


def test_llm_audit_round_trips_by_campaign_session_and_turn(
    surreal_repository: SurrealRepository,
) -> None:
    campaign = surreal_repository.create_campaign(
        title="LLMAuditRoundTrip", min_n=1, max_n=3
    )
    session = surreal_repository.start_interview_session(
        campaign_id=campaign.id,
        invite_id=None,
        consent_mode="anonymous",
        identity_label="anon",
        persona_snapshot={"role": "tester"},
        pinned_endpoint="chatter",
    )
    turn = surreal_repository.append_interview_turn(
        session.id,
        role="participant",
        content="I lost a day to queue metadata.",
    )
    surreal_repository.record_llm_audit(
        {
            "campaign_id": campaign.id,
            "session_id": session.id,
            "turn_id": turn.id,
            "surface": "interviewer",
            "brain": "B",
            "role": "scientist",
            "model_alias": "mira-scientist",
            "catalog_id": "scientist-default",
            "catalog_route": "scientist",
            "endpoint": "scientist",
            "endpoint_model": "local-scientist",
            "latency_ms": 12,
            "status": "ok",
            "prompt_tokens": 5,
            "completion_tokens": 6,
            "total_tokens": 11,
            "reasoning_tokens": 2,
            "reasoning_metadata": {"thinking_enabled": False},
        }
    )

    rows = surreal_repository.list_llm_audits(
        campaign_id=campaign.id,
        session_id=session.id,
        turn_id=turn.id,
    )

    assert len(rows) == 1
    assert rows[0].campaign_id == campaign.id
    assert rows[0].session_id == session.id
    assert rows[0].turn_id == turn.id
    assert rows[0].brain == "B"
    assert rows[0].total_tokens == 11


def test_list_knowledge_sources_by_status_filters_correctly(
    surreal_repository: SurrealRepository,
) -> None:
    campaign = surreal_repository.create_campaign(
        title="StatusFilter", min_n=1, max_n=3
    )
    queued = surreal_repository.create_knowledge_source(
        campaign_id=campaign.id,
        kind="url",
        title="queued-src",
        hash_value="hash-queued",
        url="https://example.test/q",
        status="queued",
    )
    surreal_repository.create_knowledge_source(
        campaign_id=campaign.id,
        kind="url",
        title="approved-src",
        hash_value="hash-approved",
        url="https://example.test/a",
        status="approved",
    )

    queued_sources = surreal_repository.list_knowledge_sources_by_status(["queued"])
    queued_ids = {src.id for src in queued_sources}
    assert queued.id in queued_ids
    # Returned rows all carry the requested status.
    assert all(src.status == "queued" for src in queued_sources)
