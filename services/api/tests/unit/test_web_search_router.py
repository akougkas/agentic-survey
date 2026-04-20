from __future__ import annotations

import asyncio

import pytest

from agentic_survey.services.web_search.base import WebSearchResult
from agentic_survey.services.web_search.router import WebSearchError, search


class _FakeBackend:
    def __init__(
        self,
        name: str,
        *,
        results: list[WebSearchResult] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self._results = results or []
        self._error = error
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, top_k: int) -> list[WebSearchResult]:
        self.calls.append((query, top_k))
        if self._error is not None:
            raise self._error
        return list(self._results)


def _sample(source: str, n: int = 2) -> list[WebSearchResult]:
    return [
        WebSearchResult(
            title=f"{source} hit {i}",
            url=f"https://{source}.example/{i}",
            snippet=f"snippet {i}",
            source=source,
        )
        for i in range(n)
    ]


def test_router_returns_searxng_results_when_primary_succeeds() -> None:
    searxng = _FakeBackend("searxng", results=_sample("searxng", 3))
    ddg = _FakeBackend("ddg", results=_sample("ddg", 3))

    results = asyncio.run(search("qualitative saturation", top_k=5, backends=[searxng, ddg]))

    assert [r.source for r in results] == ["searxng"] * 3
    assert searxng.calls == [("qualitative saturation", 5)]
    assert ddg.calls == []


def test_router_falls_back_to_ddg_when_searxng_raises() -> None:
    searxng = _FakeBackend("searxng", error=RuntimeError("connection refused"))
    ddg = _FakeBackend("ddg", results=_sample("ddg", 2))

    results = asyncio.run(search("interview methodology", top_k=10, backends=[searxng, ddg]))

    assert [r.source for r in results] == ["ddg", "ddg"]
    assert searxng.calls == [("interview methodology", 10)]
    assert ddg.calls == [("interview methodology", 10)]


def test_router_raises_when_all_backends_fail() -> None:
    searxng = _FakeBackend("searxng", error=RuntimeError("searxng down"))
    ddg = _FakeBackend("ddg", error=RuntimeError("ddg down"))

    with pytest.raises(WebSearchError) as exc_info:
        asyncio.run(search("anything", top_k=3, backends=[searxng, ddg]))

    err = exc_info.value
    assert [name for name, _ in err.errors] == ["searxng", "ddg"]
    assert "searxng down" in str(err)
    assert "ddg down" in str(err)


def test_router_empty_primary_does_not_trigger_fallback() -> None:
    searxng = _FakeBackend("searxng", results=[])
    ddg = _FakeBackend("ddg", results=_sample("ddg", 1))

    results = asyncio.run(search("no hits", top_k=5, backends=[searxng, ddg]))

    assert results == []
    assert ddg.calls == []


def test_router_rejects_blank_query() -> None:
    searxng = _FakeBackend("searxng", results=_sample("searxng"))
    with pytest.raises(ValueError):
        asyncio.run(search("   ", top_k=5, backends=[searxng]))


def test_router_rejects_non_positive_top_k() -> None:
    searxng = _FakeBackend("searxng", results=_sample("searxng"))
    with pytest.raises(ValueError):
        asyncio.run(search("ok", top_k=0, backends=[searxng]))


def test_router_raises_when_no_backends_configured() -> None:
    with pytest.raises(WebSearchError):
        asyncio.run(search("ok", top_k=5, backends=[]))
