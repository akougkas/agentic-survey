"""Integration test for hybrid retrieval (BM25 + vector + RRF).

Builds a synthetic campaign where:
- BM25 alone misses chunks A/B (lexical mismatch against the query).
- Vector alone misses chunks C/D (lexical match that semantic embedding
  doesn't bring to the top).
- Hybrid RRF recovers A/B/C at recall@5.

Because the in-memory BM25 is a word-overlap stand-in and the in-memory
vector path is cosine similarity over hand-picked embeddings, we can drive
both deterministically without touching SurrealDB.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agentic_survey.repository import InMemoryRepository
from agentic_survey.services.retrieval import search_knowledge


class _QueryRouter:
    """Returns a fixed 768-dim vector regardless of input.

    Tests that rely on ordering set up the chunk embeddings so the stored
    vectors span the 768-dim space meaningfully via the first few dims;
    the rest are zero-padded to 768 so :class:`embed_query` accepts them.
    """

    def __init__(self, vector: list[float]) -> None:
        self._vector = list(vector)
        self.call_count = 0

    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        self.call_count += 1
        return {"data": [{"embedding": list(self._vector)} for _ in input]}


def _pad(prefix: list[float]) -> list[float]:
    tail = [0.0] * (768 - len(prefix))
    return list(prefix) + tail


def _seed_corpus(repo: InMemoryRepository) -> str:
    campaign = repo.create_campaign(title="Demo", min_n=5, max_n=10)
    source = repo.create_knowledge_source(
        campaign_id=campaign.id,
        kind="raw_text",
        title="Corpus",
        hash_value="corpus",
        status="approved",
    )

    # Chunks A & B: embedding close to the query vector but content that
    # does NOT contain the query term "saturation" — BM25 will miss them.
    # Chunks C & D: contain "saturation" but embedding orthogonal to query —
    # BM25 wins them, vector alone misses.
    # Chunk E: both — the easy case.
    # Plus 15 distractors to pad to 20 total.
    specs = [
        ("A", "Theme development stabilises when no new categories emerge.", _pad([1.0, 0.0])),
        ("B", "Coding reaches a plateau as incoming data reiterates existing codes.", _pad([0.99, 0.1])),
        ("C", "Saturation means we stop sampling new participants.", _pad([0.0, 1.0])),
        ("D", "The saturation point depends on the sample's heterogeneity.", _pad([0.0, 0.99])),
        ("E", "Saturation heuristics: no new codes after five consecutive interviews.", _pad([0.8, 0.2])),
    ]
    distractors = [
        (f"X{i}", f"unrelated filler content about project management {i}", _pad([0.0, 0.0, 1.0]))
        for i in range(15)
    ]
    specs.extend(distractors)

    chunk_ids: dict[str, str] = {}
    for index, (label, content, vec) in enumerate(specs):
        chunk = repo.create_knowledge_chunk(
            campaign_id=campaign.id,
            source_id=source.id,
            content=content,
            position=index,
            char_start=0,
            char_end=len(content),
            approved=True,
        )
        repo.update_knowledge_chunk_embedding(chunk.id, vec)
        chunk_ids[label] = chunk.id

    return campaign.id


def test_hybrid_recovers_both_lexical_and_semantic_hits() -> None:
    repo = InMemoryRepository()
    campaign_id = _seed_corpus(repo)
    # Query vector aligned with A/B/E semantic region.
    router = _QueryRouter(_pad([1.0, 0.0]))

    hits = asyncio.run(
        search_knowledge(
            campaign_id=campaign_id,
            query="saturation",
            k=5,
            mode="hybrid",
            repository=repo,
            surface="designer",
            router=router,
        )
    )
    ids = [hit.chunk_id for hit in hits]

    # Find the chunk ids we seeded so we can recover the semantic labels.
    by_content = {
        chunk.content.split(".")[0]: chunk.id
        for chunk in repo._knowledge_chunks.values()
    }
    label_ids = {
        "A": by_content["Theme development stabilises when no new categories emerge"],
        "B": by_content["Coding reaches a plateau as incoming data reiterates existing codes"],
        "C": by_content["Saturation means we stop sampling new participants"],
    }
    recovered = {lbl for lbl, cid in label_ids.items() if cid in ids}
    missing = {"A", "B", "C"} - recovered
    assert not missing, f"hybrid recall@5 missed labels {missing}; ids={ids}"


def test_bm25_only_misses_semantic_hits() -> None:
    repo = InMemoryRepository()
    campaign_id = _seed_corpus(repo)
    router = _QueryRouter(_pad([1.0, 0.0]))

    hits = asyncio.run(
        search_knowledge(
            campaign_id=campaign_id,
            query="saturation",
            k=5,
            mode="bm25",
            repository=repo,
            surface="designer",
            router=router,
        )
    )
    ids = [hit.chunk_id for hit in hits]
    # BM25 alone must not call the embedding router.
    assert router.call_count == 0
    # The semantic-only hits (A/B) should NOT appear in BM25-only results.
    by_content = {
        chunk.content.split(".")[0]: chunk.id
        for chunk in repo._knowledge_chunks.values()
    }
    a_id = by_content["Theme development stabilises when no new categories emerge"]
    b_id = by_content["Coding reaches a plateau as incoming data reiterates existing codes"]
    assert a_id not in ids
    assert b_id not in ids


def test_vector_only_hits_semantic_neighbors() -> None:
    repo = InMemoryRepository()
    campaign_id = _seed_corpus(repo)
    router = _QueryRouter(_pad([1.0, 0.0]))

    hits = asyncio.run(
        search_knowledge(
            campaign_id=campaign_id,
            query="saturation",
            k=3,
            mode="vector",
            repository=repo,
            surface="designer",
            router=router,
        )
    )
    ids = [hit.chunk_id for hit in hits]
    by_content = {
        chunk.content.split(".")[0]: chunk.id
        for chunk in repo._knowledge_chunks.values()
    }
    a_id = by_content["Theme development stabilises when no new categories emerge"]
    b_id = by_content["Coding reaches a plateau as incoming data reiterates existing codes"]
    # Vector-only should bring back the semantic twins of the query vector.
    assert a_id in ids
    assert b_id in ids
    # Exactly one aembedding call was made (batch-of-1).
    assert router.call_count == 1
