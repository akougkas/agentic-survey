from __future__ import annotations

import asyncio

from agentic_survey.bundles import SeedSource
from agentic_survey.repository import InMemoryRepository
from agentic_survey.services.knowledge_ingest import ingest_seed_sources


def _campaign(repo: InMemoryRepository):
    return repo.create_campaign(title="Autoapprove demo", min_n=3, max_n=8)


def test_raw_text_seed_lands_approved() -> None:
    repo = InMemoryRepository()
    campaign = _campaign(repo)
    seed = SeedSource(
        kind="raw_text",
        title="Scientist-curated brief",
        content_inline=(
            "Saturation in qualitative interviews is declared when the "
            "marginal probe yields no new axis signal for two consecutive "
            "turns on every rubric dimension."
        ),
    )
    result = asyncio.run(ingest_seed_sources(campaign.id, [seed], repo))
    assert len(result.created_source_ids) == 1
    source_id = result.created_source_ids[0]
    source = repo.get_knowledge_source(source_id)
    assert source is not None
    assert source.status == "approved"
    assert source.approved_by == "bundle_seed_autoapproval"
    chunks = repo.list_knowledge_chunks_for_source(source_id)
    assert chunks, "expected at least one chunk for raw_text seed"
    assert all(chunk.approved for chunk in chunks)


def test_url_seed_stays_queued() -> None:
    repo = InMemoryRepository()
    campaign = _campaign(repo)
    seed = SeedSource(
        kind="url",
        title="External anchor",
        url="https://example.com/anchor",
    )
    result = asyncio.run(ingest_seed_sources(campaign.id, [seed], repo))
    assert len(result.created_source_ids) == 1
    source_id = result.created_source_ids[0]
    source = repo.get_knowledge_source(source_id)
    assert source is not None
    assert source.status == "queued"
    assert repo.count_chunks_for_source(source_id) == 0
