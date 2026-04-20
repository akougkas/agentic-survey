from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentic_survey.api.knowledge import router as knowledge_router
from agentic_survey.auth import require_admin_session
from agentic_survey.repository import InMemoryRepository, get_repository
from agentic_survey.services.ingestion.embed import EmbeddingError, embed_chunks


class _ShortVectorRouter:
    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        return {"data": [{"embedding": [0.1] * 512} for _ in input]}


class _GoodRouter:
    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        return {"data": [{"embedding": [0.01] * 768} for _ in input]}


class _MissingDataRouter:
    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        return {"choices": []}


def test_embed_chunks_raises_on_dimension_mismatch() -> None:
    with pytest.raises(EmbeddingError) as exc:
        asyncio.run(embed_chunks(["hello"], router=_ShortVectorRouter()))
    assert "dimension" in str(exc.value)


def test_embed_chunks_raises_when_data_key_missing() -> None:
    with pytest.raises(EmbeddingError):
        asyncio.run(embed_chunks(["hello"], router=_MissingDataRouter()))


def test_embed_chunks_raises_when_batch_count_mismatches() -> None:
    class _CountMismatch:
        async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
            return {"data": [{"embedding": [0.0] * 768}]}  # only 1 back for 2 in

    with pytest.raises(EmbeddingError):
        asyncio.run(embed_chunks(["a", "b"], router=_CountMismatch()))


def test_embed_chunks_batches_above_batch_size() -> None:
    router = _GoodRouter()
    texts = [f"chunk-{i}" for i in range(33)]
    vecs = asyncio.run(embed_chunks(texts, router=router, batch_size=16))
    assert len(vecs) == 33
    for vec in vecs:
        assert len(vec) == 768


# --- API endpoint tests ---------------------------------------------------


def _build_app() -> tuple[FastAPI, InMemoryRepository]:
    repo = InMemoryRepository()
    app = FastAPI()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.include_router(knowledge_router, prefix="/api")
    return app, repo


def test_upload_url_returns_404_for_unknown_campaign() -> None:
    app, _ = _build_app()
    client = TestClient(app)
    response = client.post(
        "/api/admin/campaigns/does-not-exist/knowledge/upload-url",
        json={"url": "https://example.com/a"},
    )
    assert response.status_code == 404


def test_upload_url_auto_detects_pdf_with_query_and_fragment() -> None:
    app, repo = _build_app()
    campaign = repo.create_campaign(title="Demo", min_n=5, max_n=10)
    client = TestClient(app)

    response = client.post(
        f"/api/admin/campaigns/{campaign.id}/knowledge/upload-url",
        json={"url": "https://host.example/paper.pdf?dl=1#page=2"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source"]["kind"] == "pdf"
    assert body["source"]["status"] == "queued"


def test_upload_url_queues_url_sources_with_rationale() -> None:
    app, repo = _build_app()
    campaign = repo.create_campaign(title="Demo", min_n=5, max_n=10)
    client = TestClient(app)

    response = client.post(
        f"/api/admin/campaigns/{campaign.id}/knowledge/upload-url",
        json={
            "url": "https://en.wikipedia.org/wiki/Research_design",
            "title": "Research design",
            "rationale": "Smoke",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source"]["kind"] == "url"
    assert body["source"]["rationale"] == "Smoke"
    assert body["source"]["status"] == "queued"
