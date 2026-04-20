from __future__ import annotations

import asyncio
from typing import Any

from agentic_survey.engine.graph_builder import apply_validator_to_graph
from agentic_survey.repository import InMemoryRepository


class _StubRouter:
    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        return {"data": [{"embedding": [0.0] + [0.1] * 767} for _ in input]}


def _setup() -> tuple[InMemoryRepository, str, Any]:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Edges", min_n=3, max_n=6)
    return repo, campaign.id, _StubRouter()


def _validation(labels: list[str]) -> dict:
    return {
        "extracted_concepts": [{"label": label, "type": ""} for label in labels],
        "extracted_relations": [],
    }


def test_three_concepts_emit_three_co_occurrence_edges() -> None:
    repo, campaign_id, router = _setup()

    delta = asyncio.run(
        apply_validator_to_graph(
            campaign_id=campaign_id,
            session_id="session-1",
            turn_id="turn-1",
            validation=_validation(["Reproducibility", "Replication", "Preregistration"]),
            repository=repo,
            router=router,
        )
    )

    assert len(delta.light_up) == 3
    assert len(delta.add_nodes) == 3
    # C(3, 2) = 3 co-occurrence edges.
    assert len(delta.add_edges) == 3
    for edge in delta.add_edges:
        assert edge["kind"] == "co_occurrence"
        assert edge["edge_table"] == "mentioned_with"
        assert edge["confidence"] == 1.0
    assert len(repo._graph_edges) == 3


def test_overlapping_turns_accumulate_edges_and_mention_counts() -> None:
    repo, campaign_id, router = _setup()

    first = asyncio.run(
        apply_validator_to_graph(
            campaign_id=campaign_id,
            session_id="session-1",
            turn_id="turn-1",
            validation=_validation(["Saturation", "Replication"]),
            repository=repo,
            router=router,
        )
    )
    second = asyncio.run(
        apply_validator_to_graph(
            campaign_id=campaign_id,
            session_id="session-1",
            turn_id="turn-2",
            validation=_validation(["Saturation", "Validity"]),
            repository=repo,
            router=router,
        )
    )

    # Turn 1 created 2 new nodes; turn 2 created 1 new node (Validity).
    assert len(first.add_nodes) == 2
    assert len(second.add_nodes) == 1
    assert {node["label"] for node in second.add_nodes} == {"validity"}
    # Edges land in their own row per turn; they don't merge.
    assert len(first.add_edges) == 1
    assert len(second.add_edges) == 1
    assert len(repo._graph_edges) == 2
    # The shared "saturation" concept has mention_count=2 by end of turn 2.
    shared_id = repo._concept_by_label[(campaign_id, "saturation")]
    shared = repo.get_concept(shared_id)
    assert shared is not None and shared.mention_count == 2


def test_self_pair_dedupe_produces_no_self_edge() -> None:
    repo, campaign_id, router = _setup()

    delta = asyncio.run(
        apply_validator_to_graph(
            campaign_id=campaign_id,
            session_id="session-1",
            turn_id="turn-1",
            validation=_validation(["Saturation", "saturation", "SATURATION"]),
            repository=repo,
            router=router,
        )
    )

    # After normalization all three labels collapse to one concept.
    assert len(delta.light_up) == 1
    assert len(delta.add_nodes) == 1
    # No self-pair edge is emitted.
    assert delta.add_edges == []
    assert repo._graph_edges == []


def test_single_concept_turn_emits_no_edges() -> None:
    repo, campaign_id, router = _setup()

    delta = asyncio.run(
        apply_validator_to_graph(
            campaign_id=campaign_id,
            session_id="session-1",
            turn_id="turn-1",
            validation=_validation(["Saturation"]),
            repository=repo,
            router=router,
        )
    )

    assert len(delta.light_up) == 1
    assert len(delta.add_edges) == 0


def test_empty_validation_is_noop() -> None:
    repo, campaign_id, router = _setup()

    delta = asyncio.run(
        apply_validator_to_graph(
            campaign_id=campaign_id,
            session_id="session-1",
            turn_id="turn-1",
            validation={"extracted_concepts": [], "extracted_relations": []},
            repository=repo,
            router=router,
        )
    )
    assert delta.add_nodes == []
    assert delta.add_edges == []
    assert delta.light_up == []
