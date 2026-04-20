"""Concept graph writes + neighborhood reads against live Surreal.

Exercises ``merge_concept`` idempotency, the ``mentioned_with`` and
``contradicts`` RELATE paths, and ``list_concept_neighborhood``. M5's
unit suite covers only the InMemory paths; this tier verifies the
SurrealQL that ships.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from agentic_survey.db.surreal_repository import SurrealRepository


class _DeterministicRouter:
    """Returns a label-derived 768-dim vector so merge_concept works offline."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        self.calls.append(list(input))
        return {
            "data": [
                {"embedding": _vector_for_label(text)} for text in input
            ]
        }


def _vector_for_label(label: str, dim: int = 768) -> list[float]:
    """Deterministic pseudo-random 768-dim vector keyed on the label."""
    digest = hashlib.sha256(label.encode("utf-8")).digest()
    # Expand the digest to `dim` floats in [-1, 1).
    values: list[float] = []
    buf = digest
    while len(values) < dim:
        buf = hashlib.sha256(buf).digest() + buf
        for b in buf[:32]:
            values.append((b / 127.5) - 1.0)
            if len(values) >= dim:
                break
    return values


def _prepare_session(
    repo: SurrealRepository, *, title: str
) -> tuple[str, str, str]:
    """Create campaign + interview session + first turn for RELATE targets."""
    campaign = repo.create_campaign(title=title, min_n=1, max_n=3)
    session = repo.start_interview_session(
        campaign_id=campaign.id,
        invite_id=None,
        consent_mode="anonymous",
        identity_label="anon",
        persona_snapshot={"role": "tester"},
        pinned_endpoint="mini",
    )
    turn = repo.append_interview_turn(
        session.id,
        role="participant",
        content="Starting context for graph writes",
    )
    return campaign.id, session.id, turn.id


def test_merge_concept_is_idempotent(surreal_repository: SurrealRepository) -> None:
    campaign_id, _, _ = _prepare_session(surreal_repository, title="MergeConcept")
    router = _DeterministicRouter()

    first = asyncio.run(
        surreal_repository.merge_concept(
            campaign_id=campaign_id,
            label="Observability",
            type="practice",
            router=router,
        )
    )
    assert first.is_new is True
    assert first.mention_count == 1
    assert first.type == "practice"

    second = asyncio.run(
        surreal_repository.merge_concept(
            campaign_id=campaign_id,
            label="OBSERVABILITY",  # case-insensitive normalization
            type="concept",  # type on a hit is ignored; first value wins
            router=router,
        )
    )
    assert second.is_new is False
    assert second.id == first.id
    assert second.mention_count == 2
    assert second.type == "practice"
    # Router only runs on misses.
    assert len(router.calls) == 1


def test_record_mentioned_with_and_neighborhood(
    surreal_repository: SurrealRepository,
) -> None:
    campaign_id, session_id, turn_id = _prepare_session(
        surreal_repository, title="Neighborhood"
    )
    router = _DeterministicRouter()

    a = asyncio.run(
        surreal_repository.merge_concept(
            campaign_id=campaign_id,
            label="Sampling",
            type="method",
            router=router,
        )
    )
    b = asyncio.run(
        surreal_repository.merge_concept(
            campaign_id=campaign_id,
            label="Saturation",
            type="method",
            router=router,
        )
    )

    surreal_repository.record_mentioned_with(
        campaign_id=campaign_id,
        session_id=session_id,
        turn_id=turn_id,
        from_id=a.id,
        to_id=b.id,
        kind="co_occurrence",
        confidence=0.8,
    )

    result = surreal_repository.list_concept_neighborhood(
        campaign_id=campaign_id, label="sampling", depth=1, k=8
    )
    assert result["center"] is not None
    assert result["center"]["id"] == a.id
    node_ids = {node["id"] for node in result["nodes"]}
    assert {a.id, b.id} <= node_ids
    kinds = {edge["kind"] for edge in result["edges"]}
    assert "co_occurrence" in kinds


def test_record_contradicts_appears_in_neighborhood(
    surreal_repository: SurrealRepository,
) -> None:
    campaign_id, session_id, turn_id = _prepare_session(
        surreal_repository, title="Contradicts"
    )
    router = _DeterministicRouter()

    a = asyncio.run(
        surreal_repository.merge_concept(
            campaign_id=campaign_id,
            label="Structured protocol",
            type="approach",
            router=router,
        )
    )
    b = asyncio.run(
        surreal_repository.merge_concept(
            campaign_id=campaign_id,
            label="Emergent protocol",
            type="approach",
            router=router,
        )
    )

    surreal_repository.record_contradicts(
        campaign_id=campaign_id,
        session_id=session_id,
        turn_id=turn_id,
        from_id=a.id,
        to_id=b.id,
        confidence=0.95,
    )

    result = surreal_repository.list_concept_neighborhood(
        campaign_id=campaign_id, label="structured protocol", depth=1, k=8
    )
    # The edge should surface with the canonical "contradicts" kind.
    edges = result["edges"]
    assert edges, "contradicts edge did not appear in neighborhood"
    found = [
        edge
        for edge in edges
        if edge["edge_table"] == "contradicts" and edge["from"] == a.id
    ]
    assert found, f"expected contradicts edge from {a.id}; got {edges}"
    assert found[0]["confidence"] == 0.95


def test_list_concept_neighborhood_returns_empty_for_unknown_label(
    surreal_repository: SurrealRepository,
) -> None:
    campaign_id, _, _ = _prepare_session(surreal_repository, title="Unknown")
    result = surreal_repository.list_concept_neighborhood(
        campaign_id=campaign_id,
        label="nothing-was-ever-stored",
        depth=1,
        k=4,
    )
    assert result == {"center": None, "nodes": [], "edges": []}


def test_list_graph_edges_merges_both_edge_tables(
    surreal_repository: SurrealRepository,
) -> None:
    campaign_id, session_id, turn_id = _prepare_session(
        surreal_repository, title="EdgeMerge"
    )
    router = _DeterministicRouter()

    a = asyncio.run(
        surreal_repository.merge_concept(
            campaign_id=campaign_id, label="alpha", type="", router=router
        )
    )
    b = asyncio.run(
        surreal_repository.merge_concept(
            campaign_id=campaign_id, label="beta", type="", router=router
        )
    )
    c = asyncio.run(
        surreal_repository.merge_concept(
            campaign_id=campaign_id, label="gamma", type="", router=router
        )
    )
    surreal_repository.record_mentioned_with(
        campaign_id=campaign_id,
        session_id=session_id,
        turn_id=turn_id,
        from_id=a.id,
        to_id=b.id,
        kind="co_occurrence",
        confidence=0.5,
    )
    surreal_repository.record_contradicts(
        campaign_id=campaign_id,
        session_id=session_id,
        turn_id=turn_id,
        from_id=b.id,
        to_id=c.id,
        confidence=0.6,
    )

    edges = surreal_repository.list_graph_edges_for_campaign(campaign_id)
    tables = {edge["edge_table"] for edge in edges}
    assert {"mentioned_with", "contradicts"} <= tables
