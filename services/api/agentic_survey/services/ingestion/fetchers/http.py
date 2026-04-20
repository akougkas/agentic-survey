from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger(__name__)

__all__ = ["FetcherError", "Tier1Insufficient", "fetch_html"]


class FetcherError(RuntimeError):
    """Base error for fetcher failures that should mark a source ``failed``."""


class Tier1Insufficient(FetcherError):
    """Tier-1 extraction returned content below ``min_chars`` or nothing at all.

    Raising this is the signal to the pipeline that a tier-2 escalation may
    be warranted (via ``SURVEY_INGEST_CRAWL4AI``). The pipeline catches it and
    either escalates or marks the source ``failed``.
    """


_DEFAULT_HEADERS = {
    "User-Agent": (
        "AgenticSurveyIngestor/0.1 "
        "(+https://github.com/akougkas/agentic-survey; compatible)"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
}

_WHITESPACE_RE = re.compile(r"[ \t]+")
_NEWLINE_COLLAPSE_RE = re.compile(r"\n{3,}")


async def fetch_html(
    url: str,
    *,
    min_chars: int = 500,
    timeout_seconds: float = 30.0,
) -> str:
    """Download a URL and extract readable text via readability-lxml.

    Raises ``FetcherError`` on HTTP failure or unusable payload and
    ``Tier1Insufficient`` when the extracted body is shorter than
    ``min_chars``. The pipeline decides whether to escalate.
    """
    if not url:
        raise FetcherError("url is empty")

    try:
        async with httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers=_DEFAULT_HEADERS,
        ) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        raise FetcherError(f"httpx transport failed: {exc}") from exc

    if response.status_code >= 400:
        raise FetcherError(f"HTTP {response.status_code} for {url}")

    content_type = (response.headers.get("content-type") or "").lower()
    if "html" not in content_type and "xml" not in content_type:
        logger.warning(
            "fetch_html: unexpected content-type %r for url=%s", content_type, url
        )

    html = response.text or ""
    extracted = _extract_readable(html)
    normalized = _normalize_whitespace(extracted)
    if len(normalized) < min_chars:
        raise Tier1Insufficient(
            f"extracted {len(normalized)} chars (<{min_chars}) from {url}"
        )
    return normalized


def _extract_readable(html: str) -> str:
    """Run readability-lxml on the raw HTML; return plain text."""
    try:
        from readability import Document  # readability-lxml
    except ImportError as exc:  # pragma: no cover - dep is a required runtime dep
        raise FetcherError("readability-lxml not installed") from exc

    try:
        doc = Document(html)
        summary_html = doc.summary(html_partial=True)
    except Exception as exc:
        raise Tier1Insufficient(f"readability failed: {exc}") from exc

    try:
        from lxml import html as lxml_html
    except ImportError as exc:  # pragma: no cover
        raise FetcherError("lxml not installed (readability-lxml transitive)") from exc

    try:
        tree = lxml_html.fromstring(summary_html)
    except Exception as exc:
        raise Tier1Insufficient(f"lxml parse failed: {exc}") from exc

    text = tree.text_content() or ""
    return text.strip()


def _normalize_whitespace(text: str) -> str:
    collapsed_spaces = _WHITESPACE_RE.sub(" ", text)
    lines = [line.strip() for line in collapsed_spaces.splitlines()]
    joined = "\n".join(line for line in lines if line)
    return _NEWLINE_COLLAPSE_RE.sub("\n\n", joined).strip()
