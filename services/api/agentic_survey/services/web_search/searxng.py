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
        # Always bind the timeout to the request so a reused injected
        # client cannot hang the caller. httpx treats a request-level
        # timeout as an override of the client-level default.
        if self._client is not None:
            response = await self._client.get(
                url,
                params=params,
                timeout=self.timeout_seconds,
            )
        else:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or "results" not in payload:
            # Treat a malformed response as a backend failure so the
            # router can fall back to DDG instead of returning an empty
            # list that terminates the chain.
            raise RuntimeError("searxng: response missing 'results' key")
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise RuntimeError(
                f"searxng: 'results' is {type(raw_results).__name__}, expected list"
            )
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
