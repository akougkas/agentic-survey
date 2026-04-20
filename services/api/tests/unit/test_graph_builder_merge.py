from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agentic_survey.engine.graph_builder import apply_validator_to_graph
from agentic_survey.repository import InMemoryRepository


class _RouterCountingEmbedding:
    """Records every aembedding call so tests can assert on embed volume."""

    def __init__(self, dim: int = 768) -> None:
        self.dim = dim
        self.calls: list[list[str]] = []

    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        self.calls.append(list(input))
        return {
            "data": [
                {"embedding": [0.01 * (idx + 1)] * self.dim}
                for idx, _ in enumerate(input)
            ]
        }


def _campaign(repo: InMemoryRepository, title: str = "Demo") -> str:
    return repo.create_campaign(title=title, min_n=3, max_n=6).id


def test_merge_concept_first_call_inserts_and_embeds() -> None:
    repo = InMemoryRepository()
    campaign_id = _campaign(repo)
    router = _RouterCountingEmbedding()

    concept = asyncio.run(
        repo.merge_concept(
            campaign_id=campaign_id,
            label="Saturation",
            type="concept",
            router=router,
        )
    )

    assert concept.is_new is True
    assert concept.mention_count == 1
    assert concept.label == "saturation"
    assert concept.type == "concept"
    vec = repo.get_concept_embedding(concept.id)
    assert vec is not None
    assert len(vec) == 768
    assert len(router.calls) == 1


def test_merge_concept_repeat_mention_skips_embedding() -> None:
    repo = InMemoryRepository()
    campaign_id = _campaign(repo)
    router = _RouterCountingEmbedding()

    first = asyncio.run(
        repo.merge_concept(
            campaign_id=campaign_id,
            label="Saturation",
            type="concept",
            router=router,
        )
    )
    second = asyncio.run(
        repo.merge_concept(
            campaign_id=campaign_id,
            label="saturation ",
            type="different",
            router=router,
        )
    )
    third = asyncio.run(
        repo.merge_concept(
            campaign_id=campaign_id,
            label="SATURATION",
            type="concept",
            router=router,
        )
    )

    assert first.id == second.id == third.id
    assert first.is_new is True
    assert second.is_new is False
    assert third.is_new is False
    assert third.mention_count == 3
    # Type preserved from the first insert; not overwritten on re-mention.
    assert third.type == "concept"
    # Counter-mock the router to assert embedding is called once across repeats.
    assert len(router.calls) == 1


def test_merge_concept_scoped_per_campaign() -> None:
    repo = InMemoryRepository()
    campaign_a = _campaign(repo, title="A")
    campaign_b = _campaign(repo, title="B")
    router = _RouterCountingEmbedding()

    concept_a = asyncio.run(
        repo.merge_concept(
            campaign_id=campaign_a,
            label="context",
            type="",
            router=router,
        )
    )
    concept_b = asyncio.run(
        repo.merge_concept(
            campaign_id=campaign_b,
            label="context",
            type="",
            router=router,
        )
    )

    assert concept_a.id != concept_b.id
    assert concept_a.campaign_id == campaign_a
    assert concept_b.campaign_id == campaign_b
    # Each campaign embedded the label on its first insert.
    assert len(router.calls) == 2


def test_merge_concept_rejects_empty_labels() -> None:
    repo = InMemoryRepository()
    campaign_id = _campaign(repo)
    router = _RouterCountingEmbedding()

    with pytest.raises(ValueError):
        asyncio.run(
            repo.merge_concept(
                campaign_id=campaign_id,
                label="   ",
                type="",
                router=router,
            )
        )
    # Embedding must not be called for a rejected label.
    assert router.calls == []


def test_apply_validator_to_graph_normalizes_before_merge() -> None:
    repo = InMemoryRepository()
    campaign_id = _campaign(repo)
    router = _RouterCountingEmbedding()

    validation = {
        "extracted_concepts": [
            {"label": "Saturation", "type": "concept"},
            {"label": "saturation", "type": "concept"},
            {"label": "  ", "type": "noise"},
            {"label": "Replication", "type": "concept"},
        ],
        "extracted_relations": [],
    }
    delta = asyncio.run(
        apply_validator_to_graph(
            campaign_id=campaign_id,
            session_id="session-stub",
            turn_id="turn-stub",
            validation=validation,
            repository=repo,
            router=router,
        )
    )
    # Duplicate after normalization drops to one concept; blank label is
    # skipped; two unique concepts remain.
    assert len(delta.light_up) == 2
    assert len(delta.add_nodes) == 2
    # Only the two unique labels hit the embedder.
    assert len(router.calls) == 2
