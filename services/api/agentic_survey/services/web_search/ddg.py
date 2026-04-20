from __future__ import annotations

import asyncio
from typing import Any, Callable

from agentic_survey.services.web_search.base import WebSearchResult


class DDGBackend:
    """DuckDuckGo fallback backed by the ``ddgs`` package (maintained fork).

    The ``ddgs`` API is synchronous; ``search`` runs the blocking call in a
    worker thread via ``asyncio.to_thread`` so the event loop is not pinned.
    Tests inject ``client_factory`` — a zero-arg callable returning a
    context manager with a ``text(query, max_results=...)`` method — to
    avoid real network calls.
    """

    name = "ddg"

    def __init__(self, *, client_factory: Callable[[], Any] | None = None) -> None:
        self._client_factory = client_factory

    async def search(self, query: str, top_k: int = 10) -> list[WebSearchResult]:
        factory = self._client_factory or _default_factory
        return await asyncio.to_thread(_blocking_search, factory, query, top_k, self.name)


def _default_factory() -> Any:
    from ddgs import DDGS  # type: ignore[import-not-found]

    return DDGS()


def _blocking_search(
    factory: Callable[[], Any],
    query: str,
    top_k: int,
    source_name: str,
) -> list[WebSearchResult]:
    client_cm = factory()
    # ddgs' DDGS works as a context manager in 9.x; accept plain objects too
    # so tests can pass simple stand-ins without implementing __enter__.
    if hasattr(client_cm, "__enter__") and hasattr(client_cm, "__exit__"):
        with client_cm as client:
            items = list(client.text(query, max_results=top_k))
    else:
        items = list(client_cm.text(query, max_results=top_k))
    out: list[WebSearchResult] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("href") or item.get("url") or "").strip()
        if not url:
            continue
        out.append(
            WebSearchResult(
                title=str(item.get("title") or "").strip(),
                url=url,
                snippet=str(item.get("body") or item.get("snippet") or "").strip(),
                source=source_name,
            )
        )
        if len(out) >= top_k:
            break
    return out
