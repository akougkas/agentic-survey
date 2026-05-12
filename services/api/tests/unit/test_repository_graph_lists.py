"""Campaign-scoped list helpers feed the M6 RAG export.

The Surreal side is covered by live integration; here we nail the
InMemoryRepository contract so the writer can rely on stable ordering.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from agentic_survey.engine.graph_builder import apply_validator_to_graph
from agentic_survey.repository import InMemoryRepository


class _StubRouter:
    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        return {"data": [{"embedding": [0.01] * 768} for _ in input]}


def _seed_graph(repo: InMemoryRepository, campaign_id: str, labels: list[str]) -> None:
    validation = {
        "extracted_concepts": [{"label": label, "type": "theme"} for label in labels],
        "extracted_relations": [],
    }
    asyncio.run(
        apply_validator_to_graph(
            campaign_id=campaign_id,
            session_id="sess-1",
            turn_id=f"turn-{len(labels)}",
            validation=validation,
            repository=repo,
            router=_StubRouter(),
        )
    )


def test_list_retrieval_audits_returns_oldest_first() -> None:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Audits", min_n=3, max_n=6)
    for i in range(3):
        repo.record_retrieval_audit(
            campaign_id=campaign.id,
            surface="designer",
            query=f"q{i}",
            top_k=5,
            chunk_ids=[],
            scores=[],
            mode="hybrid",
            cache_hit=False,
        )
        # Clock gap so created_at timestamps differ.
        time.sleep(0.001)

    audits = repo.list_retrieval_audits_for_campaign(campaign.id)
    assert [a.query for a in audits] == ["q0", "q1", "q2"]


def test_list_retrieval_audits_scoped_to_campaign() -> None:
    repo = InMemoryRepository()
    a = repo.create_campaign(title="A", min_n=3, max_n=6)
    b = repo.create_campaign(title="B", min_n=3, max_n=6)

    repo.record_retrieval_audit(
        campaign_id=a.id, surface="designer", query="in-a", top_k=5,
        chunk_ids=[], scores=[], mode="bm25", cache_hit=False,
    )
    repo.record_retrieval_audit(
        campaign_id=b.id, surface="interviewer", query="in-b", top_k=5,
        chunk_ids=[], scores=[], mode="hybrid", cache_hit=False,
    )

    a_audits = repo.list_retrieval_audits_for_campaign(a.id)
    b_audits = repo.list_retrieval_audits_for_campaign(b.id)
    assert [x.query for x in a_audits] == ["in-a"]
    assert [x.query for x in b_audits] == ["in-b"]


def test_validator_result_upsert_round_trips_by_turn() -> None:
    repo = InMemoryRepository()
    first = repo.upsert_validator_result(
        turn_id="turn-1",
        validation={
            "coverage_score": 0.4,
            "quality_score": 0.6,
            "follow_up_needed": True,
            "follow_up_reason": "thin concrete detail",
            "is_spam": False,
            "extracted_concepts": [{"label": "archive queue", "type": "tool"}],
            "extracted_relations": [{"source": "archive queue", "target": "beamline"}],
            "objective_tags": ["R1"],
        },
    )
    second = repo.upsert_validator_result(
        turn_id="turn-1",
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

    loaded = repo.get_validator_result("turn-1")
    assert loaded is not None
    assert second.id == first.id
    assert loaded.id == first.id
    assert loaded.coverage_score == 0.8
    assert loaded.objective_tags == ["R1", "R3"]


def test_list_concepts_returns_first_seen_ascending() -> None:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Concepts", min_n=3, max_n=6)
    _seed_graph(repo, campaign.id, ["alpha"])
    time.sleep(0.002)
    _seed_graph(repo, campaign.id, ["beta"])
    time.sleep(0.002)
    _seed_graph(repo, campaign.id, ["gamma"])

    concepts = repo.list_concepts_for_campaign(campaign.id)
    assert [c.label for c in concepts] == ["alpha", "beta", "gamma"]
    # The export does not carry ``is_new``; snapshot rows must clear it.
    assert all(c.is_new is False for c in concepts)


def test_list_concepts_scoped_to_campaign() -> None:
    repo = InMemoryRepository()
    a = repo.create_campaign(title="A", min_n=3, max_n=6)
    b = repo.create_campaign(title="B", min_n=3, max_n=6)
    _seed_graph(repo, a.id, ["one"])
    _seed_graph(repo, b.id, ["two"])
    assert [c.label for c in repo.list_concepts_for_campaign(a.id)] == ["one"]
    assert [c.label for c in repo.list_concepts_for_campaign(b.id)] == ["two"]


def test_list_graph_edges_returns_newest_first() -> None:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Edges", min_n=3, max_n=6)
    _seed_graph(repo, campaign.id, ["alpha", "beta"])
    time.sleep(0.002)
    _seed_graph(repo, campaign.id, ["alpha", "gamma"])

    edges = repo.list_graph_edges_for_campaign(campaign.id)
    # Two co-occurrence edges total, newest (alpha<->gamma turn) first.
    assert len(edges) == 2
    gamma_id = repo._concept_by_label[(campaign.id, "gamma")]
    first = edges[0]
    assert gamma_id in {first["from_id"], first["to_id"]}
    assert edges[0]["created_at"] >= edges[1]["created_at"]


def test_list_graph_edges_merges_mentioned_with_and_contradicts() -> None:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Mixed", min_n=3, max_n=6)
    validation = {
        "extracted_concepts": [
            {"label": "alpha", "type": "t"},
            {"label": "beta", "type": "t"},
        ],
        "extracted_relations": [
            {"from": "alpha", "to": "beta", "kind": "contradicts", "confidence": 0.8},
        ],
    }
    asyncio.run(
        apply_validator_to_graph(
            campaign_id=campaign.id,
            session_id="sess-1",
            turn_id="turn-1",
            validation=validation,
            repository=repo,
            router=_StubRouter(),
        )
    )

    edges = repo.list_graph_edges_for_campaign(campaign.id)
    tables = sorted(edge["edge_table"] for edge in edges)
    assert tables == ["contradicts", "mentioned_with"]
    contradict_edge = next(e for e in edges if e["edge_table"] == "contradicts")
    assert contradict_edge["kind"] == "contradicts"
    assert contradict_edge["confidence"] == 0.8


def test_empty_campaign_returns_empty_lists() -> None:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Empty", min_n=3, max_n=6)
    assert repo.list_retrieval_audits_for_campaign(campaign.id) == []
    assert repo.list_concepts_for_campaign(campaign.id) == []
    assert repo.list_graph_edges_for_campaign(campaign.id) == []
    assert repo.list_campaign_exports_for_campaign(campaign.id) == []
