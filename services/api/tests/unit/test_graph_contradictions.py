from __future__ import annotations

import asyncio
from typing import Any

from agentic_survey.engine.graph_builder import apply_validator_to_graph
from agentic_survey.repository import InMemoryRepository


class _StubRouter:
    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        return {"data": [{"embedding": [0.0] * 768} for _ in input]}


def _setup() -> tuple[InMemoryRepository, str, Any]:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Contradictions", min_n=3, max_n=6)
    return repo, campaign.id, _StubRouter()


def test_contradicts_relation_lands_in_contradicts_table() -> None:
    repo, campaign_id, router = _setup()

    validation = {
        "extracted_concepts": [
            {"label": "A", "type": ""},
            {"label": "B", "type": ""},
        ],
        "extracted_relations": [
            {"from": "A", "to": "B", "kind": "contradicts", "confidence": 0.8},
        ],
    }

    delta = asyncio.run(
        apply_validator_to_graph(
            campaign_id=campaign_id,
            session_id="session-1",
            turn_id="turn-1",
            validation=validation,
            repository=repo,
            router=router,
        )
    )

    contradicts_edges = [e for e in repo._graph_edges if e["edge_table"] == "contradicts"]
    mentioned_with_edges = [
        e for e in repo._graph_edges if e["edge_table"] == "mentioned_with"
    ]
    assert len(contradicts_edges) == 1
    contradiction = contradicts_edges[0]
    assert contradiction["confidence"] == 0.8
    # The C(2,2)=1 co-occurrence edge is in mentioned_with; the contradiction
    # is NOT duplicated into mentioned_with.
    assert len(mentioned_with_edges) == 1
    assert mentioned_with_edges[0]["kind"] == "co_occurrence"
    # The delta surfaces both edges for the SSE stream.
    edge_kinds = sorted(edge["kind"] for edge in delta.add_edges)
    assert edge_kinds == ["co_occurrence", "contradicts"]


def test_non_contradicts_kind_becomes_explicit_relation() -> None:
    repo, campaign_id, router = _setup()

    validation = {
        "extracted_concepts": [
            {"label": "causing", "type": ""},
            {"label": "effect", "type": ""},
        ],
        "extracted_relations": [
            {"from": "causing", "to": "effect", "kind": "causes", "confidence": 0.65},
        ],
    }

    delta = asyncio.run(
        apply_validator_to_graph(
            campaign_id=campaign_id,
            session_id="session-1",
            turn_id="turn-1",
            validation=validation,
            repository=repo,
            router=router,
        )
    )

    explicit = [
        e
        for e in repo._graph_edges
        if e["edge_table"] == "mentioned_with" and e["kind"] == "explicit_relation"
    ]
    assert len(explicit) == 1
    assert explicit[0]["confidence"] == 0.65
    # NOT co_occurrence for this edge (the co-occurrence is a separate row).
    co_occurrence = [
        e
        for e in repo._graph_edges
        if e["edge_table"] == "mentioned_with" and e["kind"] == "co_occurrence"
    ]
    assert len(co_occurrence) == 1
    # Delta includes both.
    kinds = sorted(edge["kind"] for edge in delta.add_edges)
    assert kinds == ["co_occurrence", "explicit_relation"]


def test_relation_endpoint_not_in_concept_list_is_merged_defensively() -> None:
    repo, campaign_id, router = _setup()

    validation = {
        "extracted_concepts": [{"label": "known", "type": ""}],
        "extracted_relations": [
            {"from": "known", "to": "novel", "kind": "causes", "confidence": 0.4},
        ],
    }

    delta = asyncio.run(
        apply_validator_to_graph(
            campaign_id=campaign_id,
            session_id="session-1",
            turn_id="turn-1",
            validation=validation,
            repository=repo,
            router=router,
        )
    )

    labels = {
        repo.get_concept(cid).label for cid in delta.light_up
    }
    assert labels == {"known", "novel"}
    # Both concepts show up as new nodes in the delta.
    new_labels = {node["label"] for node in delta.add_nodes}
    assert new_labels == {"known", "novel"}


def test_contradiction_with_same_endpoint_is_skipped() -> None:
    repo, campaign_id, router = _setup()

    validation = {
        "extracted_concepts": [{"label": "self", "type": ""}],
        "extracted_relations": [
            {"from": "self", "to": "self", "kind": "contradicts", "confidence": 0.9},
        ],
    }

    asyncio.run(
        apply_validator_to_graph(
            campaign_id=campaign_id,
            session_id="session-1",
            turn_id="turn-1",
            validation=validation,
            repository=repo,
            router=router,
        )
    )
    # Self-relation is rejected so no contradicts edge is recorded.
    assert not [e for e in repo._graph_edges if e["edge_table"] == "contradicts"]
