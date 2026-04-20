from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentic_survey.api.knowledge import (
    KnowledgeSearchRequest,  # noqa: F401  (import-only coverage)
    get_web_search,
    router as knowledge_router,
)
from agentic_survey.auth import require_admin_session
from agentic_survey.engine.state_machine import CampaignState
from agentic_survey.repository import InMemoryRepository, get_repository
from agentic_survey.services.web_search import WebSearchError, WebSearchResult


def _build_app(
    *,
    fake_results: list[WebSearchResult] | None = None,
    fake_error: Exception | None = None,
) -> tuple[FastAPI, InMemoryRepository]:
    repo = InMemoryRepository()
    app = FastAPI()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[require_admin_session] = lambda: object()

    async def _fake(query: str, top_k: int) -> list[WebSearchResult]:
        if fake_error is not None:
            raise fake_error
        return list(fake_results or [])

    def _override_web_search() -> Any:
        return _fake

    app.dependency_overrides[get_web_search] = _override_web_search
    app.include_router(knowledge_router, prefix="/api")
    return app, repo


def _sample_hits(n: int = 3, source: str = "searxng") -> list[WebSearchResult]:
    return [
        WebSearchResult(
            title=f"Result {i}",
            url=f"https://example.org/doc-{i}",
            snippet=f"A snippet about topic {i}.",
            source=source,
        )
        for i in range(n)
    ]


def test_knowledge_search_404_on_unknown_campaign() -> None:
    app, _ = _build_app(fake_results=_sample_hits())
    client = TestClient(app)

    response = client.post(
        "/api/admin/campaigns/missing-id/knowledge/search",
        json={"query": "qualitative saturation"},
    )
    assert response.status_code == 404


def test_knowledge_search_happy_path_persists_searxng_suggestions() -> None:
    hits = _sample_hits(3, source="searxng")
    app, repo = _build_app(fake_results=hits)
    campaign = repo.create_campaign(title="Demo", min_n=5, max_n=10)
    client = TestClient(app)

    response = client.post(
        f"/api/admin/campaigns/{campaign.id}/knowledge/search",
        json={"query": "qualitative interview saturation", "top_k": 10},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["campaign_id"] == campaign.id
    assert body["query"] == "qualitative interview saturation"
    assert len(body["results"]) == 3
    assert len(body["created_source_ids"]) == 3

    rows = repo.list_knowledge_sources(campaign.id)
    assert [r.kind for r in rows] == ["searxng_suggestion"] * 3
    assert all(r.status == "pending_approval" for r in rows)
    assert all(r.url and r.url.startswith("https://example.org/doc-") for r in rows)
    assert all("backend=searxng" in r.rationale for r in rows)


def test_knowledge_search_400_when_campaign_live() -> None:
    app, repo = _build_app(fake_results=_sample_hits())
    campaign = repo.create_campaign(title="Demo", min_n=5, max_n=10)
    # Walk campaign to LIVE via the legal transition chain.
    repo.advance_campaign(campaign.id, CampaignState.DESIGNING)
    repo.advance_campaign(campaign.id, CampaignState.REVIEWING)
    repo.advance_campaign(campaign.id, CampaignState.LIVE)
    client = TestClient(app)

    response = client.post(
        f"/api/admin/campaigns/{campaign.id}/knowledge/search",
        json={"query": "anything"},
    )

    assert response.status_code == 400
    assert "design-time" in response.json()["detail"]
    # No rows written.
    assert repo.list_knowledge_sources(campaign.id) == []


def test_knowledge_search_400_when_campaign_monitoring() -> None:
    app, repo = _build_app(fake_results=_sample_hits())
    campaign = repo.create_campaign(title="Demo", min_n=5, max_n=10)
    repo.advance_campaign(campaign.id, CampaignState.DESIGNING)
    repo.advance_campaign(campaign.id, CampaignState.REVIEWING)
    repo.advance_campaign(campaign.id, CampaignState.LIVE)
    repo.advance_campaign(campaign.id, CampaignState.MONITORING)
    client = TestClient(app)

    response = client.post(
        f"/api/admin/campaigns/{campaign.id}/knowledge/search",
        json={"query": "anything"},
    )

    assert response.status_code == 400


def test_knowledge_search_502_when_all_backends_down() -> None:
    error = WebSearchError(
        "all backends down",
        errors=[("searxng", RuntimeError("x")), ("ddg", RuntimeError("y"))],
    )
    app, repo = _build_app(fake_error=error)
    campaign = repo.create_campaign(title="Demo", min_n=5, max_n=10)
    client = TestClient(app)

    response = client.post(
        f"/api/admin/campaigns/{campaign.id}/knowledge/search",
        json={"query": "qualitative saturation"},
    )

    assert response.status_code == 502
    # No rows written on backend failure.
    assert repo.list_knowledge_sources(campaign.id) == []


def test_knowledge_search_rejects_empty_query() -> None:
    app, repo = _build_app(fake_results=_sample_hits())
    campaign = repo.create_campaign(title="Demo", min_n=5, max_n=10)
    client = TestClient(app)

    response = client.post(
        f"/api/admin/campaigns/{campaign.id}/knowledge/search",
        json={"query": ""},
    )
    assert response.status_code == 422
