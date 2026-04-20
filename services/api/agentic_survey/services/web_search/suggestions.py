from __future__ import annotations

import hashlib
from typing import Iterable

from agentic_survey.engine.state_machine import CampaignState
from agentic_survey.repository import KnowledgeSource
from agentic_survey.services.web_search.base import WebSearchResult

__all__ = [
    "SearchSuggestionsRejected",
    "assert_design_time",
    "queue_proposed_queries",
    "queue_search_results",
]

_PROPOSED_QUERY_TAG = "source=brain_b_designer"
_RESULT_RATIONALE_MAX = 480


class SearchSuggestionsRejected(RuntimeError):
    """Raised when a search-suggestion write is attempted while the campaign
    has already crossed into the live interview phase. Design-time only.
    """


def assert_design_time(state: CampaignState | str) -> None:
    """Reject web-search writes once the campaign is live or monitoring.

    Accepts either a ``CampaignState`` or the raw string to make call-site
    glue (API handlers read from Pydantic, closures from the Campaign
    model) uniform.
    """
    value = state.value if isinstance(state, CampaignState) else str(state)
    if value in (CampaignState.LIVE.value, CampaignState.MONITORING.value):
        raise SearchSuggestionsRejected(
            f"Web search is design-time only; campaign state is {value}."
        )


def queue_search_results(
    *,
    campaign_id: str,
    query: str,
    results: Iterable[WebSearchResult],
    repository,
) -> list[KnowledgeSource]:
    """Persist backend hits as ``kind="searxng_suggestion"`` rows.

    One row per result with the target URL preserved so the scientist can
    approve or reject each hit from the knowledge rail. ``rationale`` keeps
    the query that produced the hit plus the snippet, both truncated so the
    payload stays under the repository's ``title[:240]`` / prose budget.
    """
    created: list[KnowledgeSource] = []
    query_text = (query or "").strip()
    for result in results:
        url = (result.url or "").strip()
        if not url:
            continue
        title = (result.title or url).strip() or url
        snippet = (result.snippet or "").strip()
        rationale = f"query={query_text}\nbackend={result.source}\nsnippet={snippet}"
        if len(rationale) > _RESULT_RATIONALE_MAX:
            rationale = rationale[:_RESULT_RATIONALE_MAX]
        hash_value = hashlib.sha256(f"{query_text}|{url}".encode("utf-8")).hexdigest()
        source = repository.create_knowledge_source(
            campaign_id=campaign_id,
            kind="searxng_suggestion",
            title=title[:240],
            hash_value=hash_value,
            url=url,
            rationale=rationale,
            status="pending_approval",
        )
        created.append(source)
    return created


def queue_proposed_queries(
    *,
    campaign_id: str,
    queries: Iterable[str],
    repository,
) -> list[str]:
    """Persist Mira-proposed search queries as ``searxng_suggestion`` stubs.

    These rows have ``url=None`` and a tag in ``rationale`` so the UI can
    separate "Mira proposed this query" from "search returned this hit".
    Returns the list of created ``knowledge_source`` IDs.
    """
    source_ids: list[str] = []
    for raw in queries:
        query = (raw or "").strip()
        if not query:
            continue
        title = query[:240]
        rationale = f"{_PROPOSED_QUERY_TAG}\nquery={query}"
        if len(rationale) > _RESULT_RATIONALE_MAX:
            rationale = rationale[:_RESULT_RATIONALE_MAX]
        hash_value = hashlib.sha256(f"proposed_query|{query}".encode("utf-8")).hexdigest()
        source = repository.create_knowledge_source(
            campaign_id=campaign_id,
            kind="searxng_suggestion",
            title=title,
            hash_value=hash_value,
            url=None,
            rationale=rationale,
            status="pending_approval",
        )
        source_ids.append(source.id)
    return source_ids
