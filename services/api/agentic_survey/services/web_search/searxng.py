from __future__ import annotations

import httpx

from agentic_survey.services.web_search.base import WebSearchResult


class SearxngBackend:
    """SearXNG JSON-API client. Port of ``tools/searxng.py::SearxngClient``.

    Returns ``list[WebSearchResult]`` and raises on HTTP / parse failure so
    ``web_search.router`` can fall back to DuckDuckGo. The base URL comes
    from ``SURVEY_SEARXNG_URL``; an injected ``httpx.AsyncClient`` is used
    by tests, otherwise a fresh short-lived client is created per call.
    """

    name = "searxng"

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client = client

    async def search(self, query: str, top_k: int = 10) -> list[WebSearchResult]:
        params = {"q": query, "format": "json"}
        url = f"{self.base_url}/search"
        if self._client is not None:
            response = await self._client.get(url, params=params)
        else:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
        raw_results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(raw_results, list):
            return []
        out: list[WebSearchResult] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            result_url = str(item.get("url") or "").strip()
            if not result_url:
                continue
            out.append(
                WebSearchResult(
                    title=str(item.get("title") or "").strip(),
                    url=result_url,
                    snippet=str(item.get("content") or "").strip(),
                    source=self.name,
                )
            )
            if len(out) >= top_k:
                break
        return out
