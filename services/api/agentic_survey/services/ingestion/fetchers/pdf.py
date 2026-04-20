from __future__ import annotations

import io
import logging
import re

import httpx

from agentic_survey.services.ingestion.fetchers.http import FetcherError, Tier1Insufficient

logger = logging.getLogger(__name__)

__all__ = ["fetch_pdf", "extract_pdf_text"]

_WHITESPACE_RE = re.compile(r"[ \t]+")
_NEWLINE_COLLAPSE_RE = re.compile(r"\n{3,}")
_DEFAULT_HEADERS = {
    "User-Agent": (
        "AgenticSurveyIngestor/0.1 "
        "(+https://github.com/akougkas/agentic-survey; compatible)"
    ),
    "Accept": "application/pdf,*/*;q=0.8",
}


async def fetch_pdf(
    url: str,
    *,
    min_chars: int = 500,
    timeout_seconds: float = 60.0,
) -> str:
    """Download a PDF and return its plain-text body.

    Tier-2 (crawl4ai) has no useful escalation for PDFs, so short results
    still raise ``Tier1Insufficient`` so the pipeline can mark the source
    ``failed`` with context.
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

    payload = response.content or b""
    if not payload:
        raise Tier1Insufficient(f"empty PDF body for {url}")

    text = extract_pdf_text(payload)
    if len(text) < min_chars:
        raise Tier1Insufficient(
            f"extracted {len(text)} chars (<{min_chars}) from PDF {url}"
        )
    return text


def extract_pdf_text(payload: bytes) -> str:
    """Extract plain text from PDF bytes using ``pypdf``."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - pypdf is a required dep
        raise FetcherError("pypdf not installed") from exc

    try:
        reader = PdfReader(io.BytesIO(payload))
    except Exception as exc:
        raise Tier1Insufficient(f"pypdf parse failed: {exc}") from exc

    pages: list[str] = []
    for idx, page in enumerate(reader.pages):
        try:
            page_text = page.extract_text() or ""
        except Exception as exc:
            logger.warning("pypdf extract_text failed on page %d: %s", idx, exc)
            continue
        if page_text.strip():
            pages.append(page_text)

    if not pages:
        raise Tier1Insufficient("pypdf returned no text from any page")
    return _normalize_whitespace("\n\n".join(pages))


def _normalize_whitespace(text: str) -> str:
    collapsed_spaces = _WHITESPACE_RE.sub(" ", text)
    lines = [line.strip() for line in collapsed_spaces.splitlines()]
    joined = "\n".join(line for line in lines if line)
    return _NEWLINE_COLLAPSE_RE.sub("\n\n", joined).strip()
