"""BM25 and vector KNN queries against a live SurrealDB.

Seeds 768-dim embeddings directly instead of routing through the real
embedder so the test stays offline. Covers the two hot retrieval paths
plus the approved-only filter, which the unit suite exercises only
against ``InMemoryRepository``.
"""

from __future__ import annotations

from agentic_survey.db.surreal_repository import SurrealRepository
from agentic_survey.repository import KnowledgeChunk


def _basis(dim_index: int, *, dim: int = 768, scale: float = 1.0) -> list[float]:
    """Standard basis vector with ``scale`` in slot ``dim_index``."""
    vec = [0.0] * dim
    vec[dim_index] = scale
    return vec


def _seed_corpus(
    repo: SurrealRepository, *, title: str = "KnowledgeQueries"
) -> tuple[str, list[KnowledgeChunk]]:
    campaign = repo.create_campaign(title=title, min_n=3, max_n=5)
    source = repo.create_knowledge_source(
        campaign_id=campaign.id,
        kind="raw_text",
        title=f"{title}::seed",
        hash_value=f"hash-{title}",
        status="approved",
    )
    contents = [
        "Qualitative research emphasizes saturation as a stopping criterion.",
        "Survey design depends on accurate sampling frames and inclusion rules.",
        "Latency budgets for embeddings limit real-time retrieval throughput.",
    ]
    chunks: list[KnowledgeChunk] = []
    running_offset = 0
    for position, content in enumerate(contents):
        chunk = repo.create_knowledge_chunk(
            campaign_id=campaign.id,
            source_id=source.id,
            content=content,
            position=position,
            char_start=running_offset,
            char_end=running_offset + len(content),
            approved=True,
        )
        chunks.append(chunk)
        running_offset += len(content) + 1
    for position, chunk in enumerate(chunks):
        repo.update_knowledge_chunk_embedding(chunk.id, _basis(position))
    return campaign.id, chunks


def test_bm25_ranks_matching_chunk_first(surreal_repository: SurrealRepository) -> None:
    campaign_id, chunks = _seed_corpus(surreal_repository, title="BM25Research")
    hits = surreal_repository.search_knowledge_chunks_bm25(
        campaign_id=campaign_id,
        query="qualitative research saturation",
        k=3,
    )
    assert hits, "BM25 returned no rows for an obvious keyword match"
    # Chunk 0 carries "qualitative research" and "saturation"; it must win.
    assert hits[0].chunk_id == chunks[0].id
    assert hits[0].content.startswith("Qualitative research")


def test_bm25_empty_query_returns_nothing(
    surreal_repository: SurrealRepository,
) -> None:
    campaign_id, _ = _seed_corpus(surreal_repository, title="BM25Empty")
    hits = surreal_repository.search_knowledge_chunks_bm25(
        campaign_id=campaign_id,
        query="sklabsdjfoijwefpaoeirhgoiewhrg",
        k=3,
    )
    assert hits == []


def test_vector_search_orders_by_cosine_similarity(
    surreal_repository: SurrealRepository,
) -> None:
    campaign_id, chunks = _seed_corpus(surreal_repository, title="VectorBasis")
    # Query aligned with chunk 1's basis vector — that row must rank first.
    target = _basis(1)
    hits = surreal_repository.search_knowledge_chunks_vector(
        campaign_id=campaign_id,
        vector=target,
        k=3,
    )
    assert hits, "vector search returned no rows"
    assert hits[0].chunk_id == chunks[1].id
    # Perfect alignment scores 1.0 (cosine similarity).
    assert hits[0].score > 0.99


def test_vector_search_skips_unapproved(
    surreal_repository: SurrealRepository,
) -> None:
    campaign = surreal_repository.create_campaign(
        title="VectorUnapproved", min_n=3, max_n=5
    )
    source = surreal_repository.create_knowledge_source(
        campaign_id=campaign.id,
        kind="raw_text",
        title="seed",
        hash_value="hash-vec-un",
        status="pending_approval",
    )
    approved = surreal_repository.create_knowledge_chunk(
        campaign_id=campaign.id,
        source_id=source.id,
        content="approved content",
        position=0,
        char_start=0,
        char_end=16,
        approved=True,
    )
    unapproved = surreal_repository.create_knowledge_chunk(
        campaign_id=campaign.id,
        source_id=source.id,
        content="pending content",
        position=1,
        char_start=16,
        char_end=31,
        approved=False,
    )
    surreal_repository.update_knowledge_chunk_embedding(approved.id, _basis(0))
    surreal_repository.update_knowledge_chunk_embedding(unapproved.id, _basis(0))

    hits = surreal_repository.search_knowledge_chunks_vector(
        campaign_id=campaign.id,
        vector=_basis(0),
        k=5,
    )
    returned = {hit.chunk_id for hit in hits}
    assert approved.id in returned
    assert unapproved.id not in returned


def test_update_knowledge_chunk_embedding_rejects_wrong_dimension(
    surreal_repository: SurrealRepository,
) -> None:
    campaign = surreal_repository.create_campaign(title="BadDim", min_n=1, max_n=3)
    source = surreal_repository.create_knowledge_source(
        campaign_id=campaign.id,
        kind="raw_text",
        title="seed",
        hash_value="hash-bad-dim",
        status="pending_approval",
    )
    chunk = surreal_repository.create_knowledge_chunk(
        campaign_id=campaign.id,
        source_id=source.id,
        content="content",
        position=0,
        char_start=0,
        char_end=7,
    )
    try:
        surreal_repository.update_knowledge_chunk_embedding(chunk.id, [0.1, 0.2, 0.3])
    except ValueError as exc:
        assert "768" in str(exc)
        return
    raise AssertionError("768-dim guard did not fire")
