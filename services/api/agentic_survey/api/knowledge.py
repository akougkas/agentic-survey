from __future__ import annotations

import hashlib
import logging
from typing import Awaitable, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from agentic_survey.auth import require_admin_session
from agentic_survey.repository import (
    InMemoryRepository,
    KnowledgeSource,
    get_repository,
)
from agentic_survey.services.web_search import (
    WebSearchError,
    WebSearchResult,
    search as run_web_search,
)
from agentic_survey.services.web_search.suggestions import (
    SearchSuggestionsRejected,
    assert_design_time,
    queue_search_results,
)

# Kept module-level so tests can override via dependency without patching.
WebSearchFn = Callable[[str, int], Awaitable[list[WebSearchResult]]]

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/campaigns",
    tags=["knowledge"],
    dependencies=[Depends(require_admin_session)],
)


class KnowledgeSourceSummary(BaseModel):
    source: KnowledgeSource
    chunk_count: int


class KnowledgeListResponse(BaseModel):
    campaign_id: str
    by_status: dict[str, list[KnowledgeSourceSummary]] = Field(default_factory=dict)
    total: int = 0


class ApprovalResponse(BaseModel):
    source: KnowledgeSource
    chunk_count: int


class BulkApprovalResponse(BaseModel):
    approved_source_ids: list[str]
    approved_chunk_count: int


@router.get("/{campaign_id}/knowledge")
async def list_knowledge(
    campaign_id: str,
    repository: InMemoryRepository = Depends(get_repository),
) -> KnowledgeListResponse:
    if repository.get_campaign(campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    sources = repository.list_knowledge_sources(campaign_id)
    by_status: dict[str, list[KnowledgeSourceSummary]] = {}
    for source in sources:
        summary = KnowledgeSourceSummary(
            source=source,
            chunk_count=repository.count_chunks_for_source(source.id),
        )
        by_status.setdefault(source.status, []).append(summary)
    return KnowledgeListResponse(
        campaign_id=campaign_id,
        by_status=by_status,
        total=len(sources),
    )


@router.post("/{campaign_id}/knowledge/{source_id}/approve")
async def approve_knowledge_source(
    campaign_id: str,
    source_id: str,
    repository: InMemoryRepository = Depends(get_repository),
) -> ApprovalResponse:
    source = repository.get_knowledge_source(source_id)
    if source is None or source.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    updated = repository.update_knowledge_source_status(
        source_id,
        status="approved",
        approved_by="scientist",
    )
    return ApprovalResponse(
        source=updated,
        chunk_count=repository.count_chunks_for_source(source_id),
    )


@router.post("/{campaign_id}/knowledge/{source_id}/reject")
async def reject_knowledge_source(
    campaign_id: str,
    source_id: str,
    repository: InMemoryRepository = Depends(get_repository),
) -> ApprovalResponse:
    source = repository.get_knowledge_source(source_id)
    if source is None or source.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    updated = repository.update_knowledge_source_status(source_id, status="rejected")
    return ApprovalResponse(
        source=updated,
        chunk_count=repository.count_chunks_for_source(source_id),
    )


class EnqueueUrlRequest(BaseModel):
    url: HttpUrl
    title: str = ""
    kind: Literal["url", "pdf"] = "url"
    rationale: str = ""


class EnqueueResponse(BaseModel):
    source: KnowledgeSource


@router.post("/{campaign_id}/knowledge/upload-url")
async def upload_url_source(
    campaign_id: str,
    payload: EnqueueUrlRequest,
    repository: InMemoryRepository = Depends(get_repository),
) -> EnqueueResponse:
    """Queue a URL (or a remote PDF) for the ingestion worker to fetch.

    Auto-detects PDF from the path suffix when ``kind`` is left at the
    default ``url``. The worker walks the new row through
    ``queued → fetching → extracting → chunking → embedding →
    pending_approval`` and the scientist approves via the knowledge rail.
    """
    if repository.get_campaign(campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    url = str(payload.url).strip()
    kind: Literal["url", "pdf"] = payload.kind
    if kind == "url":
        # Strip ``?query`` and ``#fragment`` before checking the suffix so
        # links like ``.../paper.pdf?dl=1#page=2`` are still classified.
        bare = url.lower().split("?", 1)[0].split("#", 1)[0]
        if bare.endswith(".pdf"):
            kind = "pdf"

    title = payload.title.strip() or url
    hash_value = hashlib.sha256(url.encode("utf-8")).hexdigest()
    source = repository.create_knowledge_source(
        campaign_id=campaign_id,
        kind=kind,
        title=title[:240],
        hash_value=hash_value,
        url=url,
        rationale=payload.rationale.strip(),
        status="queued",
    )
    logger.info(
        "queued knowledge_source id=%s kind=%s url=%s campaign=%s",
        source.id,
        source.kind,
        source.url,
        campaign_id,
    )
    return EnqueueResponse(source=source)


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(default=10, ge=1, le=50)


class KnowledgeSearchResultItem(BaseModel):
    title: str
    url: str
    snippet: str
    source: str


class KnowledgeSearchResponse(BaseModel):
    campaign_id: str
    query: str
    results: list[KnowledgeSearchResultItem] = Field(default_factory=list)
    created_source_ids: list[str] = Field(default_factory=list)


async def _default_web_search(query: str, top_k: int) -> list[WebSearchResult]:
    return await run_web_search(query, top_k=top_k)


def get_web_search() -> WebSearchFn:
    """FastAPI dependency returning the active web-search callable.

    Tests override via ``app.dependency_overrides[get_web_search] = ...``
    so a fake backend can inject deterministic results without hitting
    SearXNG or DDG. Production wiring resolves through
    ``services/web_search/router.search``.
    """
    return _default_web_search


@router.post("/{campaign_id}/knowledge/search")
async def search_knowledge_suggestions(
    campaign_id: str,
    payload: KnowledgeSearchRequest,
    repository: InMemoryRepository = Depends(get_repository),
    web_search: WebSearchFn = Depends(get_web_search),
) -> KnowledgeSearchResponse:
    """Scientist-gated design-time web search.

    Runs SearXNG (primary) or DDG (fallback) and persists each hit as a
    ``knowledge_source(kind="searxng_suggestion", status="pending_approval")``
    row so the scientist can approve or reject from the knowledge rail.
    Rejects 400 when the campaign is LIVE or MONITORING; rejects 404 when
    the campaign does not exist; rejects 502 when every backend failed.
    Never mounted on the interview surface.
    """
    campaign = repository.get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    try:
        assert_design_time(campaign.state)
    except SearchSuggestionsRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        raw_results = await web_search(payload.query, payload.top_k)
    except WebSearchError as exc:
        logger.warning(
            "web_search all backends failed campaign=%s query=%r errors=%s",
            campaign_id,
            payload.query,
            [name for name, _ in exc.errors],
        )
        raise HTTPException(
            status_code=502,
            detail=f"Web search failed: {exc}",
        ) from exc

    created = queue_search_results(
        campaign_id=campaign_id,
        query=payload.query,
        results=raw_results,
        repository=repository,
    )
    logger.info(
        "web_search campaign=%s query=%r returned=%d queued=%d",
        campaign_id,
        payload.query,
        len(raw_results),
        len(created),
    )
    return KnowledgeSearchResponse(
        campaign_id=campaign_id,
        query=payload.query,
        results=[
            KnowledgeSearchResultItem(
                title=r.title,
                url=r.url,
                snippet=r.snippet,
                source=r.source,
            )
            for r in raw_results
        ],
        created_source_ids=[src.id for src in created],
    )


@router.post("/{campaign_id}/knowledge/approve-all-seeds")
async def approve_all_seeds(
    campaign_id: str,
    repository: InMemoryRepository = Depends(get_repository),
) -> BulkApprovalResponse:
    """Demo convenience: bulk-approve every pending bundle_seed for this campaign.

    Not a substitute for the per-source approval workflow. Use when the
    scientist has already blessed the mounted bundle and wants to skip the
    per-card click-through during a demo. Sources in states other than
    ``pending_approval`` are left alone.
    """
    if repository.get_campaign(campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    approved_ids: list[str] = []
    chunk_count = 0
    for source in repository.list_knowledge_sources(campaign_id):
        if source.kind != "bundle_seed" or source.status != "pending_approval":
            continue
        repository.update_knowledge_source_status(
            source.id,
            status="approved",
            approved_by="bulk_approve_seeds",
        )
        approved_ids.append(source.id)
        chunk_count += repository.count_chunks_for_source(source.id)
    return BulkApprovalResponse(
        approved_source_ids=approved_ids,
        approved_chunk_count=chunk_count,
    )
