"""Every retrieval call writes exactly one audit row carrying ``mode`` and
``cache_hit``. These tests verify both fields round-trip through the
in-memory repository for all three modes and both cache states.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agentic_survey.engine.retrieval_cache import RetrievalCache
from agentic_survey.repository import InMemoryRepository
from agentic_survey.services.retrieval import search_knowledge


class _Router:
    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
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
            content=f"saturation note {i}",
            position=i,
            char_start=0,
            char_end=20,
            approved=True,
        )
        repo.update_knowledge_chunk_embedding(chunk.id, [0.1] * 768)
    return campaign.id


def _latest_audit(repo: InMemoryRepository, campaign_id: str):
    ids = repo._retrieval_audits_by_campaign.get(campaign_id, [])
    assert ids, "expected at least one audit row"
    return repo.get_retrieval_audit(ids[-1])


def test_audit_row_records_bm25_mode() -> None:
    repo = InMemoryRepository()
    campaign_id = _seed(repo)
    asyncio.run(
        search_knowledge(
            campaign_id=campaign_id,
            query="saturation",
            k=3,
            mode="bm25",
            repository=repo,
            surface="designer",
            router=_Router(),
        )
    )
    audit = _latest_audit(repo, campaign_id)
    assert audit.mode == "bm25"
    assert audit.cache_hit is False


def test_audit_row_records_vector_mode() -> None:
    repo = InMemoryRepository()
    campaign_id = _seed(repo)
    asyncio.run(
        search_knowledge(
            campaign_id=campaign_id,
            query="saturation",
            k=3,
            mode="vector",
            repository=repo,
            surface="designer",
            router=_Router(),
        )
    )
    audit = _latest_audit(repo, campaign_id)
    assert audit.mode == "vector"
    assert audit.cache_hit is False


def test_audit_row_records_hybrid_mode() -> None:
    repo = InMemoryRepository()
    campaign_id = _seed(repo)
    asyncio.run(
        search_knowledge(
            campaign_id=campaign_id,
            query="saturation",
            k=3,
            mode="hybrid",
            repository=repo,
            surface="designer",
            router=_Router(),
        )
    )
    audit = _latest_audit(repo, campaign_id)
    assert audit.mode == "hybrid"
    assert audit.cache_hit is False


def test_audit_cache_hit_records_true_and_preserves_chunk_ids() -> None:
    repo = InMemoryRepository()
    campaign_id = _seed(repo)
    cache = RetrievalCache()
    router = _Router()

    # Cold call: writes cache_hit=false audit.
    cold = asyncio.run(
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
    cold_audit = _latest_audit(repo, campaign_id)
    assert cold_audit.cache_hit is False
    cold_chunk_ids = [hit.chunk_id for hit in cold]
    assert cold_audit.chunk_ids == cold_chunk_ids

    # Warm call: cache hit → audit.cache_hit=true + same chunk ids.
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
    warm_audit = _latest_audit(repo, campaign_id)
    assert warm_audit.cache_hit is True
    assert warm_audit.mode == "hybrid"
    assert warm_audit.chunk_ids == cold_chunk_ids


def test_cache_hit_returns_hydrated_chunk_content() -> None:
    """Regression: cache hits must rehydrate content from the repository.

    A prior implementation returned ``ChunkHit(content="")`` on cache hits,
    which fed Brain B empty strings on repeated queries within a session.
    This test proves the rehydration path pulls real content.
    """
    repo = InMemoryRepository()
    campaign_id = _seed(repo)
    cache = RetrievalCache()
    router = _Router()

    cold = asyncio.run(
        search_knowledge(
            campaign_id=campaign_id,
            query="saturation",
            k=3,
            mode="hybrid",
            repository=repo,
            surface="interviewer",
            router=router,
            session_id="sess-x",
            cache=cache,
        )
    )
    assert all(hit.content for hit in cold)

    warm = asyncio.run(
        search_knowledge(
            campaign_id=campaign_id,
            query="saturation",
            k=3,
            mode="hybrid",
            repository=repo,
            surface="interviewer",
            router=router,
            session_id="sess-x",
            cache=cache,
        )
    )
    assert len(warm) == len(cold)
    for warm_hit, cold_hit in zip(warm, cold):
        assert warm_hit.chunk_id == cold_hit.chunk_id
        assert warm_hit.content == cold_hit.content
        assert warm_hit.source_id == cold_hit.source_id


def test_audit_raises_when_repository_write_fails() -> None:
    """Invariant: audit write failure surfaces, never hidden.

    Operator rolled out M4 code but forgot to apply 0002 migration? The
    route must return 500, not silently drop the audit.
    """
    repo = InMemoryRepository()
    campaign_id = _seed(repo)

    def _boom(**_kwargs):
        raise RuntimeError("schema_migration 0002 not applied")

    repo.record_retrieval_audit = _boom  # type: ignore[method-assign]

    import pytest

    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            search_knowledge(
                campaign_id=campaign_id,
                query="saturation",
                k=3,
                mode="hybrid",
                repository=repo,
                surface="designer",
                router=_Router(),
            )
        )
    assert "schema_migration 0002" in str(exc.value)


def test_audit_row_written_exactly_once_per_call() -> None:
    repo = InMemoryRepository()
    campaign_id = _seed(repo)
    asyncio.run(
        search_knowledge(
            campaign_id=campaign_id,
            query="saturation",
            k=3,
            mode="hybrid",
            repository=repo,
            surface="designer",
            router=_Router(),
        )
    )
    assert len(repo._retrieval_audits_by_campaign[campaign_id]) == 1
