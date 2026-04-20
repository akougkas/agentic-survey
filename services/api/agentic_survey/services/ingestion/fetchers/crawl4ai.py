from __future__ import annotations

import asyncio
import logging
import re

from agentic_survey.services.ingestion.fetchers.http import FetcherError, Tier1Insufficient

logger = logging.getLogger(__name__)

__all__ = ["fetch_with_crawl4ai"]

_WHITESPACE_RE = re.compile(r"[ \t]+")
_NEWLINE_COLLAPSE_RE = re.compile(r"\n{3,}")
_DEFAULT_TIMEOUT_SECONDS = 60.0


async def fetch_with_crawl4ai(
    url: str,
    *,
    min_chars: int = 500,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Tier-2 fetcher: ``crawl4ai.AsyncWebCrawler`` with ``magic=True``.

    Lazy-imported so the package is optional. If ``crawl4ai`` is not
    installed, raises :class:`FetcherError` with installation guidance.
    Marks sources ``failed`` (via the pipeline) when extraction still
    falls below ``min_chars``.
    """
    if not url:
        raise FetcherError("url is empty")

    try:
        from crawl4ai import AsyncWebCrawler  # type: ignore[import-not-found]
    except ImportError as exc:
        raise FetcherError(
            "crawl4ai not installed; set SURVEY_INGEST_CRAWL4AI=false or "
            "install the ingest extras (uv pip install agentic-survey-backend[ingest])"
        ) from exc

    async def _run() -> object:
        async with AsyncWebCrawler(verbose=False) as crawler:
            return await crawler.arun(
                url=url,
                magic=True,
                bypass_cache=False,
                js_code=[],
            )

    try:
        result = await asyncio.wait_for(_run(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise FetcherError(
            f"crawl4ai timed out after {timeout_seconds:.0f}s for {url}"
        ) from exc
    except Exception as exc:
        raise FetcherError(f"crawl4ai failed: {exc}") from exc

    text = _extract_text_from_crawl_result(result)
    normalized = _normalize_whitespace(text)
    if len(normalized) < min_chars:
        raise Tier1Insufficient(
            f"crawl4ai extracted {len(normalized)} chars (<{min_chars}) from {url}"
        )
    return normalized


def _extract_text_from_crawl_result(result: object) -> str:
    """Prefer markdown, fall back to cleaned_html text, then raw content.

    crawl4ai's ``CrawlResult`` shape has shifted across minor versions. Try
    the richest fields first so we don't regress if the schema evolves.
    """
    for attr in ("markdown", "cleaned_html", "fit_markdown", "extracted_content"):
        value = getattr(result, attr, None)
        if value and isinstance(value, str) and value.strip():
            if attr == "cleaned_html":
                return _strip_html(value)
            return value
    html_value = getattr(result, "html", None)
    if isinstance(html_value, str) and html_value.strip():
        return _strip_html(html_value)
    return ""


def _strip_html(html: str) -> str:
    try:
        from lxml import html as lxml_html
    except ImportError:
        return html
    try:
        tree = lxml_html.fromstring(html)
    except Exception:
        return html
    return tree.text_content() or ""


def _normalize_whitespace(text: str) -> str:
    collapsed_spaces = _WHITESPACE_RE.sub(" ", text)
    lines = [line.strip() for line in collapsed_spaces.splitlines()]
    joined = "\n".join(line for line in lines if line)
    return _NEWLINE_COLLAPSE_RE.sub("\n\n", joined).strip()
