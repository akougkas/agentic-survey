from __future__ import annotations

import asyncio
from typing import Any

from agentic_survey.repository import InMemoryRepository


class _StubRouter:
    def __init__(self, dim: int = 768) -> None:
        self.dim = dim

    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        return {
            "data": [
                {"embedding": [0.01 * (i + 1)] * self.dim}
                for i, _ in enumerate(input)
            ]
        }


def test_merge_then_list_neighborhood_roundtrips_concept_and_embedding() -> None:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Round", min_n=3, max_n=6)
    router = _StubRouter()

    concept = asyncio.run(
        repo.merge_concept(
            campaign_id=campaign.id,
            label="Observability",
            type="practice",
            router=router,
        )
    )

    # list_concept_neighborhood resolves the lowercased label.
    result = repo.list_concept_neighborhood(
        campaign_id=campaign.id, label="OBSERVABILITY", depth=1, k=8
    )
    assert result["center"]["id"] == concept.id
    assert result["center"]["type"] == "practice"
    assert result["edges"] == []
    # Side-map embedding getter mirrors get_chunk_embedding.
    vec = repo.get_concept_embedding(concept.id)
    assert vec is not None
    assert len(vec) == 768


def test_get_concept_returns_deep_copy() -> None:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Round", min_n=3, max_n=6)
    router = _StubRouter()

    concept = asyncio.run(
        repo.merge_concept(
            campaign_id=campaign.id,
            label="rigor",
            type="",
            router=router,
        )
    )
    snapshot = repo.get_concept(concept.id)
    assert snapshot is not None
    assert snapshot.mention_count == 1
    # Mutating the returned copy does not affect repo state.
    snapshot.mention_count = 999
    fresh = repo.get_concept(concept.id)
    assert fresh is not None
    assert fresh.mention_count == 1


def test_get_concept_embedding_missing_returns_none() -> None:
    repo = InMemoryRepository()
    assert repo.get_concept_embedding("concept-missing") is None
