"""Unit tests for ``InMemoryRepository.search_knowledge_chunks_vector``.

Drives brute-force cosine KNN against hand-picked embeddings so the
shared retrieval path has a real backend when SurrealDB isn't running.
"""

from __future__ import annotations

from agentic_survey.repository import InMemoryRepository


def _seed(repo: InMemoryRepository) -> tuple[str, list[tuple[str, list[float], bool]]]:
    campaign = repo.create_campaign(title="Demo", min_n=5, max_n=10)
    source = repo.create_knowledge_source(
        campaign_id=campaign.id,
        kind="raw_text",
        title="Seed",
        hash_value="seedhash",
        status="approved",
    )
    # Three approved chunks with deliberate embeddings; one unapproved; one
    # without an embedding at all. Expected ranking by cosine similarity to
    # query vector [1, 0, 0] is: A (perfect), B (~0.707), C (0.0).
    chunks = [
        ("A", [1.0, 0.0, 0.0], True),
        ("B", [1.0, 1.0, 0.0], True),
        ("C", [0.0, 1.0, 0.0], True),
        ("UN", [1.0, 0.0, 0.0], False),  # unapproved; must be excluded
    ]
    stored: list[tuple[str, list[float], bool]] = []
    for label, vec, approved in chunks:
        chunk = repo.create_knowledge_chunk(
            campaign_id=campaign.id,
            source_id=source.id,
            content=f"content-{label}",
            position=len(stored),
            char_start=0,
            char_end=10,
            approved=approved,
        )
        repo.update_knowledge_chunk_embedding(chunk.id, vec)
        stored.append((chunk.id, vec, approved))

    # Add a chunk with NO embedding to confirm it's skipped.
    no_embed = repo.create_knowledge_chunk(
        campaign_id=campaign.id,
        source_id=source.id,
        content="content-NOEMBED",
        position=len(stored),
        char_start=0,
        char_end=10,
        approved=True,
    )
    stored.append((no_embed.id, [], True))
    return campaign.id, stored


def test_vector_search_orders_by_cosine_similarity() -> None:
    repo = InMemoryRepository()
    campaign_id, stored = _seed(repo)

    hits = repo.search_knowledge_chunks_vector(
        campaign_id=campaign_id,
        vector=[1.0, 0.0, 0.0],
        k=3,
    )
    # A (perfect match) first, B second, C third.
    ids = [hit.chunk_id for hit in hits]
    approved_labels = [stored[0][0], stored[1][0], stored[2][0]]
    assert ids == approved_labels


def test_vector_search_excludes_unapproved_chunks() -> None:
    repo = InMemoryRepository()
    campaign_id, stored = _seed(repo)
    unapproved_id = stored[3][0]

    hits = repo.search_knowledge_chunks_vector(
        campaign_id=campaign_id,
        vector=[1.0, 0.0, 0.0],
        k=10,
    )
    assert unapproved_id not in [hit.chunk_id for hit in hits]


def test_vector_search_excludes_chunks_without_embedding() -> None:
    repo = InMemoryRepository()
    campaign_id, stored = _seed(repo)
    no_embed_id = stored[4][0]

    hits = repo.search_knowledge_chunks_vector(
        campaign_id=campaign_id,
        vector=[1.0, 0.0, 0.0],
        k=10,
    )
    assert no_embed_id not in [hit.chunk_id for hit in hits]


def test_vector_search_respects_k_cap() -> None:
    repo = InMemoryRepository()
    campaign_id, _ = _seed(repo)

    hits = repo.search_knowledge_chunks_vector(
        campaign_id=campaign_id,
        vector=[1.0, 0.0, 0.0],
        k=1,
    )
    assert len(hits) == 1


def test_vector_search_empty_query_vector_returns_empty() -> None:
    repo = InMemoryRepository()
    campaign_id, _ = _seed(repo)
    assert (
        repo.search_knowledge_chunks_vector(
            campaign_id=campaign_id, vector=[], k=5
        )
        == []
    )


def test_vector_search_other_campaigns_excluded() -> None:
    repo = InMemoryRepository()
    campaign_a_id, _ = _seed(repo)
    # Second campaign with one approved chunk that would dominate if leaked.
    campaign_b = repo.create_campaign(title="Other", min_n=5, max_n=10)
    source_b = repo.create_knowledge_source(
        campaign_id=campaign_b.id,
        kind="raw_text",
        title="Leak",
        hash_value="leakhash",
        status="approved",
    )
    leak = repo.create_knowledge_chunk(
        campaign_id=campaign_b.id,
        source_id=source_b.id,
        content="leaky",
        position=0,
        char_start=0,
        char_end=5,
        approved=True,
    )
    repo.update_knowledge_chunk_embedding(leak.id, [1.0, 0.0, 0.0])

    hits = repo.search_knowledge_chunks_vector(
        campaign_id=campaign_a_id,
        vector=[1.0, 0.0, 0.0],
        k=10,
    )
    assert leak.id not in [hit.chunk_id for hit in hits]
