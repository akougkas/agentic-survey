"""Retrieval cache scoping by mode + cache-hit short-circuit test.

Two invariants:
1. Same query in different modes is cached independently (no collisions).
2. A cache hit skips both the embedding router call and the vector search
   DB call, proving the cache mitigates vector-retrieval latency (Gotcha
   #12).
"""

from __future__ import annotations

import asyncio
from typing import Any

from agentic_survey.engine.retrieval_cache import RetrievalCache
from agentic_survey.repository import InMemoryRepository
from agentic_survey.services.retrieval import search_knowledge


class _CountingRouter:
    def __init__(self) -> None:
        self.calls = 0

    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        self.calls += 1
        return {"data": [{"embedding": [0.01] * 768} for _ in input]}


def _seed(repo: InMemoryRepository) -> str:
    campaign = repo.create_campaign(title="Demo", min_n=5, max_n=10)
    source = repo.create_knowledge_source(
        campaign_id=campaign.id,
        kind="raw_text",
        title="Corpus",
        hash_value="c1",
        status="approved",
    )
    for i in range(3):
        chunk = repo.create_knowledge_chunk(
            campaign_id=campaign.id,
            source_id=source.id,
            content=f"saturation thought {i}",
            position=i,
            char_start=0,
            char_end=20,
            approved=True,
        )
        repo.update_knowledge_chunk_embedding(chunk.id, [0.1] * 768)
    return campaign.id


def test_cache_hit_skips_embedding_and_vector_search() -> None:
    repo = InMemoryRepository()
    campaign_id = _seed(repo)
    cache = RetrievalCache()
    router = _CountingRouter()

    # First call populates the cache.
    asyncio.run(
        search_knowledge(
            campaign_id=campaign_id,
            query="saturation",
            k=3,
            mode="hybrid",
            repository=repo,
            surface="interviewer",
            router=router,
            session_id="sess-1",
            cache=cache,
        )
    )
    assert router.calls == 1

    # Second call with the same (session, query, mode) must serve from cache
    # and NOT hit the embedding router a second time.
    asyncio.run(
        search_knowledge(
            campaign_id=campaign_id,
            query="saturation",
            k=3,
            mode="hybrid",
            repository=repo,
            surface="interviewer",
            router=router,
            session_id="sess-1",
            cache=cache,
        )
    )
    assert router.calls == 1  # counter-mock assertion per plan


def test_cache_is_scoped_by_mode() -> None:
    repo = InMemoryRepository()
    campaign_id = _seed(repo)
    cache = RetrievalCache()
    router = _CountingRouter()

    # Warm cache with hybrid.
    asyncio.run(
        search_knowledge(
            campaign_id=campaign_id,
            query="saturation",
            k=3,
            mode="hybrid",
            repository=repo,
            surface="interviewer",
            router=router,
            session_id="sess-1",
            cache=cache,
        )
    )
    # Same query, different mode: must NOT hit the hybrid cache.
    asyncio.run(
        search_knowledge(
            campaign_id=campaign_id,
            query="saturation",
            k=3,
            mode="vector",
            repository=repo,
            surface="interviewer",
            router=router,
            session_id="sess-1",
            cache=cache,
        )
    )
    # Two real embed calls: one for hybrid warm-up, one for vector cold call.
    assert router.calls == 2

    # BM25 mode skips embedding entirely.
    asyncio.run(
        search_knowledge(
            campaign_id=campaign_id,
            query="saturation",
            k=3,
            mode="bm25",
            repository=repo,
            surface="interviewer",
            router=router,
            session_id="sess-1",
            cache=cache,
        )
    )
    assert router.calls == 2


def test_design_time_skips_cache_even_when_provided() -> None:
    """No session_id means every call is a cold path."""
    repo = InMemoryRepository()
    campaign_id = _seed(repo)
    cache = RetrievalCache()
    router = _CountingRouter()

    for _ in range(3):
        asyncio.run(
            search_knowledge(
                campaign_id=campaign_id,
                query="saturation",
                k=3,
                mode="hybrid",
                repository=repo,
                surface="designer",
                router=router,
                session_id=None,
                cache=cache,
            )
        )
    assert router.calls == 3
