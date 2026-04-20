from __future__ import annotations

import logging
from typing import Iterable

from agentic_survey.config import Settings, get_settings
from agentic_survey.services.web_search.base import WebSearchBackend, WebSearchResult
from agentic_survey.services.web_search.ddg import DDGBackend
from agentic_survey.services.web_search.searxng import SearxngBackend

logger = logging.getLogger(__name__)

__all__ = ["WebSearchError", "default_backends", "search"]


class WebSearchError(RuntimeError):
    """Raised when every configured backend failed.

    Carries the per-backend exception list so callers can surface a useful
    admin error. A backend returning an empty result list is NOT a failure;
    this is only raised when every backend raised.
    """

    def __init__(
        self,
        message: str,
        *,
        errors: list[tuple[str, Exception]] | None = None,
    ) -> None:
        super().__init__(message)
        self.errors = errors or []


async def search(
    query: str,
    *,
    top_k: int | None = None,
    backends: Iterable[WebSearchBackend] | None = None,
    settings: Settings | None = None,
) -> list[WebSearchResult]:
    """Query configured backends in order; return the first successful list.

    SearXNG is primary when ``SURVEY_SEARXNG_URL`` is set (which is the
    default); DDG via the ``ddgs`` package is the fallback. If SearXNG
    raises, DDG runs. If both raise, ``WebSearchError`` is raised. A
    backend that succeeds with zero hits terminates the chain; an empty
    list is a valid answer.
    """
    q = (query or "").strip()
    if not q:
        raise ValueError("query is required and must be non-empty")
    resolved_settings = settings if settings is not None else get_settings()
    effective_top_k = top_k if top_k is not None else resolved_settings.web_search_top_k
    if effective_top_k <= 0:
        raise ValueError("top_k must be > 0")
    chain = list(backends) if backends is not None else default_backends(resolved_settings)
    if not chain:
        raise WebSearchError("no web search backends configured")
    errors: list[tuple[str, Exception]] = []
    for backend in chain:
        backend_name = getattr(backend, "name", backend.__class__.__name__)
        try:
            results = await backend.search(q, effective_top_k)
        except Exception as exc:
            logger.warning(
                "web_search backend=%s query=%r failed: %s",
                backend_name,
                q,
                exc,
            )
            errors.append((backend_name, exc))
            continue
        logger.info(
            "web_search backend=%s query=%r returned %d results",
            backend_name,
            q,
            len(results),
        )
        return results
    detail = "; ".join(f"{name}: {exc}" for name, exc in errors)
    raise WebSearchError(
        f"all web search backends failed: {detail}",
        errors=errors,
    )


def default_backends(settings: Settings) -> list[WebSearchBackend]:
    out: list[WebSearchBackend] = []
    url = (settings.searxng_url or "").strip()
    if url:
        out.append(SearxngBackend(url))
    out.append(DDGBackend())
    return out
