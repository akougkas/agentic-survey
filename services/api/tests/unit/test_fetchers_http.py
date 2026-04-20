from __future__ import annotations

import asyncio

import httpx
import pytest

from agentic_survey.services.ingestion.fetchers.http import (
    FetcherError,
    Tier1Insufficient,
    fetch_html,
)


def _fake_transport(status: int, body: str, *, content_type: str = "text/html") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=status,
            content=body.encode("utf-8"),
            headers={"content-type": content_type},
        )

    return httpx.MockTransport(handler)


def _patch_transport(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    original = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("transport", transport)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)


def test_fetch_html_extracts_body_above_min_chars(monkeypatch: pytest.MonkeyPatch) -> None:
    body = "<html><body><article>" + ("Saturation in qualitative research. " * 40) + "</article></body></html>"
    _patch_transport(monkeypatch, _fake_transport(200, body))

    text = asyncio.run(fetch_html("https://example.com/a", min_chars=100, timeout_seconds=5.0))
    assert "saturation" in text.lower()
    assert len(text) >= 100


def test_fetch_html_raises_tier1_insufficient_on_short_body(monkeypatch: pytest.MonkeyPatch) -> None:
    body = "<html><body><p>short</p></body></html>"
    _patch_transport(monkeypatch, _fake_transport(200, body))

    with pytest.raises(Tier1Insufficient):
        asyncio.run(fetch_html("https://example.com/short", min_chars=500, timeout_seconds=5.0))


def test_fetch_html_raises_fetcher_error_on_http_400(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_transport(monkeypatch, _fake_transport(403, "nope"))

    with pytest.raises(FetcherError) as exc:
        asyncio.run(fetch_html("https://example.com/denied", min_chars=10, timeout_seconds=5.0))
    assert "403" in str(exc.value)


def test_fetch_html_empty_url_raises() -> None:
    with pytest.raises(FetcherError):
        asyncio.run(fetch_html("", min_chars=10, timeout_seconds=5.0))
