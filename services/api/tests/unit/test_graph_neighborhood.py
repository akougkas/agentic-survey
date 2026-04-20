from __future__ import annotations

import asyncio
import time
from typing import Any

from agentic_survey.engine.graph_builder import apply_validator_to_graph
from agentic_survey.repository import InMemoryRepository


class _StubRouter:
    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        return {"data": [{"embedding": [0.1] * 768} for _ in input]}


def _setup() -> tuple[InMemoryRepository, str, Any]:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Neighborhood", min_n=3, max_n=6)
    return repo, campaign.id, _StubRouter()


def _run_turn(repo, campaign_id, router, session_id, turn_id, labels, relations=None):
    validation = {
        "extracted_concepts": [{"label": label, "type": ""} for label in labels],
        "extracted_relations": relations or [],
    }
    return asyncio.run(
        apply_validator_to_graph(
            campaign_id=campaign_id,
            session_id=session_id,
            turn_id=turn_id,
            validation=validation,
            repository=repo,
            router=router,
        )
    )


def test_depth_one_returns_immediate_neighbors() -> None:
    repo, campaign_id, router = _setup()
    _run_turn(repo, campaign_id, router, "s1", "t1", ["alpha", "beta", "gamma"])

    result = repo.list_concept_neighborhood(
        campaign_id=campaign_id, label="alpha", depth=1, k=8
    )

    assert result["center"]["label"] == "alpha"
    labels = {node["label"] for node in result["nodes"]}
    # Depth-1 returns the center + immediate neighbors (beta, gamma).
    assert labels == {"alpha", "beta", "gamma"}
    # Two edges touch alpha out of the three co-occurrence edges.
    assert len(result["edges"]) == 2


def test_depth_two_expands_another_hop() -> None:
    repo, campaign_id, router = _setup()
    _run_turn(repo, campaign_id, router, "s1", "t1", ["alpha", "beta"])
    _run_turn(repo, campaign_id, router, "s1", "t2", ["beta", "gamma"])
    _run_turn(repo, campaign_id, router, "s1", "t3", ["gamma", "delta"])

    result_depth_1 = repo.list_concept_neighborhood(
        campaign_id=campaign_id, label="alpha", depth=1, k=16
    )
    result_depth_2 = repo.list_concept_neighborhood(
        campaign_id=campaign_id, label="alpha", depth=2, k=16
    )

    labels_1 = {node["label"] for node in result_depth_1["nodes"]}
    labels_2 = {node["label"] for node in result_depth_2["nodes"]}
    assert labels_1 == {"alpha", "beta"}
    # Depth-2 picks up gamma via beta.
    assert {"alpha", "beta", "gamma"}.issubset(labels_2)
    assert len(result_depth_2["edges"]) >= len(result_depth_1["edges"])


def test_k_cap_limits_returned_edges() -> None:
    repo, campaign_id, router = _setup()
    _run_turn(repo, campaign_id, router, "s1", "t1", ["hub", "a", "b", "c", "d"])
    # Total edges touching "hub" = 4 at depth 1; C(5,2)=10 in the graph.

    result = repo.list_concept_neighborhood(
        campaign_id=campaign_id, label="hub", depth=1, k=2
    )
    assert len(result["edges"]) == 2


def test_missing_label_returns_empty_shell() -> None:
    repo, campaign_id, router = _setup()
    _run_turn(repo, campaign_id, router, "s1", "t1", ["alpha", "beta"])

    result = repo.list_concept_neighborhood(
        campaign_id=campaign_id, label="unknown", depth=1, k=8
    )
    assert result == {"center": None, "nodes": [], "edges": []}


def test_edges_ordered_newest_first() -> None:
    repo, campaign_id, router = _setup()
    _run_turn(repo, campaign_id, router, "s1", "t1", ["alpha", "beta"])
    # Force a clock gap so created_at timestamps differ.
    time.sleep(0.002)
    _run_turn(repo, campaign_id, router, "s1", "t2", ["alpha", "gamma"])

    result = repo.list_concept_neighborhood(
        campaign_id=campaign_id, label="alpha", depth=1, k=4
    )
    # Two edges total touching alpha; newest edge (alpha<->gamma) comes first.
    assert result["edges"]
    first = result["edges"][0]
    involved = {first["from"], first["to"]}
    gamma_id = repo._concept_by_label[(campaign_id, "gamma")]
    assert gamma_id in involved
