from __future__ import annotations

import logging
from typing import Any, Callable, Literal

from agentic_survey.repository import ChunkHit

logger = logging.getLogger(__name__)

__all__ = [
    "SearchKnowledgeFn",
    "build_search_knowledge",
    "search_knowledge",
]

Surface = Literal["designer", "interviewer"]
SearchKnowledgeFn = Callable[[str, int], "Any"]


async def search_knowledge(
    *,
    campaign_id: str,
    query: str,
    k: int,
    repository,
    surface: Surface,
) -> list[ChunkHit]:
    """Run BM25 retrieval against ``knowledge_chunk`` and audit the call.

    Results are filtered to ``approved=true`` chunks only. Every call
    writes a ``retrieval_audit`` row so the admin audit drawer can show
    what Mira saw on a given turn. On demo the ingestion path never
    auto-approves, so empty results are legitimate until the scientist
    approves in the Knowledge rail (or via the bulk-approve-seeds endpoint).
    """
    cleaned = (query or "").strip()
    if not cleaned:
        return []
    hits = repository.search_knowledge_chunks(
        campaign_id=campaign_id,
        query=cleaned,
        k=k,
    )
    try:
        repository.record_retrieval_audit(
            campaign_id=campaign_id,
            surface=surface,
            query=cleaned,
            top_k=k,
            chunk_ids=[hit.chunk_id for hit in hits],
            scores=[hit.score for hit in hits],
        )
    except Exception:
        # Audit is best-effort; never block retrieval on the audit write.
        logger.exception("retrieval_audit write failed", extra={"campaign_id": campaign_id})
    return hits


def build_search_knowledge(
    *,
    repository,
    campaign_id: str,
    surface: Surface,
) -> SearchKnowledgeFn:
    """Bind a ``search_knowledge(query, k)`` callable Brain B can call.

    The binding captures the repository, campaign, and surface so Brain B
    only has to pass the query and top-k. Both Designer and Interviewer
    Brain-B orchestrators hand this closure into ``run_brain_b_*``.
    """

    async def _bound(query: str, k: int) -> list[dict[str, Any]]:
        hits = await search_knowledge(
            campaign_id=campaign_id,
            query=query,
            k=k,
            repository=repository,
            surface=surface,
        )
        return [hit.model_dump() for hit in hits]

    return _bound
