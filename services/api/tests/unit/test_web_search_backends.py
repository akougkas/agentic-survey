from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from agentic_survey.services.web_search.searxng import SearxngBackend


class _StubResponse:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status {self.status_code}",
                request=httpx.Request("GET", "http://stub"),
                response=httpx.Response(self.status_code),
            )

    def json(self) -> Any:
        return self._payload


class _StubClient:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self._status = status
        self.calls: list[dict[str, Any]] = []

    async def get(self, url: str, **kwargs: Any) -> _StubResponse:
        self.calls.append({"url": url, **kwargs})
        return _StubResponse(self._payload, status=self._status)


def test_searxng_happy_path_maps_fields() -> None:
    payload = {
        "results": [
            {"title": "Alpha", "url": "https://example.com/a", "content": "snippet a"},
            {"title": "Beta", "url": "https://example.com/b", "content": "snippet b"},
        ]
    }
    client = _StubClient(payload)
    backend = SearxngBackend("http://searxng:8080", client=client)

    results = asyncio.run(backend.search("anything", top_k=10))

    assert len(results) == 2
    assert results[0].title == "Alpha"
    assert results[0].url == "https://example.com/a"
    assert results[0].source == "searxng"
    # Regression 2.3: injected client receives an explicit timeout kwarg.
    assert client.calls[0]["timeout"] == backend.timeout_seconds


def test_searxng_respects_top_k() -> None:
    payload = {
        "results": [
            {"title": f"t{i}", "url": f"https://example.com/{i}", "content": ""}
            for i in range(25)
        ]
    }
    backend = SearxngBackend("http://searxng:8080", client=_StubClient(payload))

    results = asyncio.run(backend.search("q", top_k=5))

    assert len(results) == 5


def test_searxng_raises_when_payload_missing_results_key() -> None:
    """Regression 2.4: malformed responses must raise so the router can
    fall back to DDG instead of returning ``[]`` and terminating the
    chain."""
    backend = SearxngBackend(
        "http://searxng:8080",
        client=_StubClient({"error": "rate limited"}),
    )

    with pytest.raises(RuntimeError, match="missing 'results'"):
        asyncio.run(backend.search("q", top_k=5))


def test_searxng_raises_when_results_is_not_a_list() -> None:
    backend = SearxngBackend(
        "http://searxng:8080",
        client=_StubClient({"results": "oops"}),
    )

    with pytest.raises(RuntimeError, match="expected list"):
        asyncio.run(backend.search("q", top_k=5))


def test_searxng_raises_on_http_error() -> None:
    backend = SearxngBackend(
        "http://searxng:8080",
        client=_StubClient({"results": []}, status=502),
    )

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(backend.search("q", top_k=5))


def test_searxng_skips_items_without_url() -> None:
    payload = {
        "results": [
            {"title": "No URL", "url": "", "content": "x"},
            {"title": "Valid", "url": "https://example.com/ok", "content": "y"},
        ]
    }
    backend = SearxngBackend(
        "http://searxng:8080",
        client=_StubClient(payload),
    )

    results = asyncio.run(backend.search("q", top_k=5))
    assert [r.title for r in results] == ["Valid"]
