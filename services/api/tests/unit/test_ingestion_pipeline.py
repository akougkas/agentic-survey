from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from agentic_survey.repository import InMemoryRepository
from agentic_survey.services.ingestion import pipeline as pipeline_module
from agentic_survey.services.ingestion.pipeline import (
    IngestionError,
    Tier1Insufficient,
    process_source,
    run_once,
)


@dataclass
class _Settings:
    ingest_min_chars: int = 20
    ingest_crawl4ai: bool = False
    ingest_http_timeout_seconds: float = 5.0
    ingest_crawl4ai_timeout_seconds: float = 5.0
    freshness_poll_seconds: int = 30


class _RouterOK:
    def __init__(self, dim: int = 768) -> None:
        self.dim = dim
        self.calls: list[list[str]] = []

    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        self.calls.append(list(input))
        return {
            "data": [
                {"embedding": [0.01 * (i + 1)] * self.dim}
                for i, _ in enumerate(input)
            ]
        }


class _RouterBoom:
    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        raise RuntimeError("embedding endpoint down")


def _seed_campaign_and_source(
    *,
    kind: str,
    url: str = "https://example.com/a",
) -> tuple[InMemoryRepository, str, str]:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Demo", min_n=5, max_n=10)
    source = repo.create_knowledge_source(
        campaign_id=campaign.id,
        kind=kind,
        title="Test source",
        hash_value="abc",
        url=url,
        status="queued",
    )
    return repo, campaign.id, source.id


def _install_fake_fetch(
    monkeypatch: pytest.MonkeyPatch, payload: str
) -> None:
    async def fake_fetch_html(url: str, **kwargs: Any) -> str:
        return payload

    monkeypatch.setattr(pipeline_module, "fetch_html", fake_fetch_html)


def _install_raising_fetch(
    monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    async def raising(url: str, **kwargs: Any) -> str:
        raise exc

    monkeypatch.setattr(pipeline_module, "fetch_html", raising)


def test_process_source_happy_path_url(monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _, source_id = _seed_campaign_and_source(kind="url")
    payload = "Saturation in qualitative research means no new themes emerge." * 20
    _install_fake_fetch(monkeypatch, payload)
    router = _RouterOK()

    asyncio.run(
        process_source(
            source_id=source_id,
            repository=repo,
            router=router,
            settings=_Settings(),
        )
    )

    final = repo.get_knowledge_source(source_id)
    assert final is not None
    assert final.status == "pending_approval"
    assert final.error_detail is None
    chunks = repo.list_knowledge_chunks_for_source(source_id)
    assert chunks, "expected at least one chunk"
    for chunk in chunks:
        vec = repo.get_chunk_embedding(chunk.id)
        assert vec is not None
        assert len(vec) == 768
    # At least one aembedding call fired.
    assert router.calls


def test_process_source_is_idempotent_on_terminal_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _, source_id = _seed_campaign_and_source(kind="url")
    repo.update_knowledge_source_status(source_id, status="pending_approval")
    _install_fake_fetch(monkeypatch, "irrelevant" * 200)

    asyncio.run(
        process_source(
            source_id=source_id,
            repository=repo,
            router=_RouterOK(),
            settings=_Settings(),
        )
    )

    # Untouched: no chunks should have been written the second time.
    chunks = repo.list_knowledge_chunks_for_source(source_id)
    assert chunks == []


def test_process_source_tier1_insufficient_without_escalation_marks_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _, source_id = _seed_campaign_and_source(kind="url")
    _install_raising_fetch(monkeypatch, Tier1Insufficient("too short"))

    with pytest.raises(Tier1Insufficient):
        asyncio.run(
            process_source(
                source_id=source_id,
                repository=repo,
                router=_RouterOK(),
                settings=_Settings(ingest_crawl4ai=False),
            )
        )

    final = repo.get_knowledge_source(source_id)
    assert final is not None
    assert final.status == "failed"
    assert final.error_detail
    assert "too short" in final.error_detail


def test_process_source_embedding_failure_marks_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _, source_id = _seed_campaign_and_source(kind="url")
    _install_fake_fetch(monkeypatch, "Content." * 100)

    with pytest.raises(Exception):
        asyncio.run(
            process_source(
                source_id=source_id,
                repository=repo,
                router=_RouterBoom(),
                settings=_Settings(),
            )
        )

    final = repo.get_knowledge_source(source_id)
    assert final is not None
    assert final.status == "failed"
    assert final.error_detail


def test_process_source_unsupported_kind_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, campaign_id, _ = _seed_campaign_and_source(kind="url")
    source = repo.create_knowledge_source(
        campaign_id=campaign_id,
        kind="raw_text",
        title="raw",
        hash_value="rawhash",
        status="queued",
    )

    with pytest.raises(IngestionError):
        asyncio.run(
            process_source(
                source_id=source.id,
                repository=repo,
                router=_RouterOK(),
                settings=_Settings(),
            )
        )

    final = repo.get_knowledge_source(source.id)
    assert final is not None
    assert final.status == "failed"


def test_run_once_drains_queued_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    repo, campaign_id, first_id = _seed_campaign_and_source(kind="url")
    second = repo.create_knowledge_source(
        campaign_id=campaign_id,
        kind="url",
        title="second",
        hash_value="hash-2",
        url="https://example.com/b",
        status="queued",
    )
    _install_fake_fetch(monkeypatch, "Content." * 150)

    completed = asyncio.run(
        run_once(repository=repo, router=_RouterOK(), settings=_Settings())
    )
    assert completed == 2
    assert repo.get_knowledge_source(first_id).status == "pending_approval"
    assert repo.get_knowledge_source(second.id).status == "pending_approval"


def test_run_once_isolates_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    repo, campaign_id, good_id = _seed_campaign_and_source(kind="url")
    bad = repo.create_knowledge_source(
        campaign_id=campaign_id,
        kind="url",
        title="broken",
        hash_value="hash-bad",
        url="https://example.com/bad",
        status="queued",
    )

    async def selective_fetch(url: str, **kwargs: Any) -> str:
        if "bad" in url:
            raise Tier1Insufficient("bad url")
        return "Content." * 150

    monkeypatch.setattr(pipeline_module, "fetch_html", selective_fetch)

    completed = asyncio.run(
        run_once(
            repository=repo,
            router=_RouterOK(),
            settings=_Settings(ingest_crawl4ai=False),
        )
    )
    assert completed == 1
    assert repo.get_knowledge_source(good_id).status == "pending_approval"
    assert repo.get_knowledge_source(bad.id).status == "failed"


def test_tier2_escalation_note_is_written_and_cleared_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _, source_id = _seed_campaign_and_source(kind="url")

    async def tier1_too_short(url: str, **kwargs: Any) -> str:
        raise Tier1Insufficient("tier-1 only returned 50 chars")

    # Stand in for the crawl4ai tier-2 import by patching the symbol on the
    # pipeline module after we assert the escalation note was written.
    monkeypatch.setattr(pipeline_module, "fetch_html", tier1_too_short)

    async def fake_crawl(url: str, *, min_chars: int, timeout_seconds: float) -> str:
        # Inspect the source while we're mid-escalation: the note should be
        # written by the pipeline before calling us.
        source = repo.get_knowledge_source(source_id)
        assert source is not None
        assert source.status == "fetching"
        assert source.error_detail is not None
        assert "tier1 insufficient" in source.error_detail
        return "Content extracted via tier-2." * 80

    import agentic_survey.services.ingestion.fetchers.crawl4ai as crawl4ai_mod

    monkeypatch.setattr(crawl4ai_mod, "fetch_with_crawl4ai", fake_crawl)

    asyncio.run(
        process_source(
            source_id=source_id,
            repository=repo,
            router=_RouterOK(),
            settings=_Settings(ingest_crawl4ai=True),
        )
    )

    final = repo.get_knowledge_source(source_id)
    assert final is not None
    assert final.status == "pending_approval"
    # Note was cleared at the final transition.
    assert final.error_detail is None


def test_progress_hook_is_invoked(monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _, source_id = _seed_campaign_and_source(kind="url")
    _install_fake_fetch(monkeypatch, "Content." * 150)

    seen: list[tuple[str, str]] = []

    async def on_progress(sid: str, status: str) -> None:
        seen.append((sid, status))

    asyncio.run(
        process_source(
            source_id=source_id,
            repository=repo,
            router=_RouterOK(),
            settings=_Settings(),
            on_progress=on_progress,
        )
    )
    statuses = [status for _, status in seen]
    assert statuses == [
        "queued",
        "fetching",
        "extracting",
        "chunking",
        "embedding",
        "pending_approval",
    ]
