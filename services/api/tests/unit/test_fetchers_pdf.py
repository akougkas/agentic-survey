from __future__ import annotations

import asyncio
import io

import httpx
import pytest

from agentic_survey.services.ingestion.fetchers.http import FetcherError, Tier1Insufficient
from agentic_survey.services.ingestion.fetchers.pdf import extract_pdf_text, fetch_pdf


def _build_pdf(body_lines: list[str]) -> bytes:
    """Tiny hand-rolled PDF that pypdf can read without extra deps.

    Uses the minimal object layout from the PDF 1.4 spec: a single page,
    one font, and a Tj string. Good enough to exercise pypdf's text
    extraction path.
    """
    try:
        from pypdf import PdfWriter
    except ImportError:  # pragma: no cover
        pytest.skip("pypdf not installed")

    # pypdf doesn't expose a "write raw text" primitive in the stable API,
    # so we use reportlab-free approach: PdfWriter.add_blank_page won't add
    # text. We build a minimal PDF from scratch instead.
    content_stream = "BT /F1 24 Tf 72 720 Td " + "".join(
        f"({line}) Tj 0 -28 Td " for line in body_lines
    ) + "ET"
    length = len(content_stream.encode("latin-1"))
    pdf = (
        "%PDF-1.4\n"
        "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        "2 0 obj << /Type /Pages /Count 1 /Kids [3 0 R] >> endobj\n"
        "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n"
        "4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
        f"5 0 obj << /Length {length} >> stream\n{content_stream}\nendstream endobj\n"
        "xref\n0 6\n0000000000 65535 f\n"
        "0000000010 00000 n\n0000000060 00000 n\n0000000111 00000 n\n"
        "0000000212 00000 n\n0000000272 00000 n\n"
        f"trailer << /Root 1 0 R /Size 6 >>\nstartxref\n{300 + length}\n%%EOF"
    )
    return pdf.encode("latin-1")


def test_extract_pdf_text_returns_body_lines() -> None:
    body = ["Saturation in qualitative research.", "Evidence of theme closure."]
    payload = _build_pdf(body)
    text = extract_pdf_text(payload)
    assert "Saturation" in text
    assert "Evidence" in text


def test_extract_pdf_text_raises_on_empty_pdf() -> None:
    # Empty pages produce no text; the extractor raises Tier1Insufficient.
    pdf = (
        "%PDF-1.4\n"
        "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        "2 0 obj << /Type /Pages /Count 1 /Kids [3 0 R] >> endobj\n"
        "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >> endobj\n"
        "xref\n0 4\n0000000000 65535 f\n"
        "0000000010 00000 n\n0000000060 00000 n\n0000000111 00000 n\n"
        "trailer << /Root 1 0 R /Size 4 >>\nstartxref\n176\n%%EOF"
    ).encode("latin-1")
    with pytest.raises(Tier1Insufficient):
        extract_pdf_text(pdf)


def _patch_transport(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    original = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("transport", transport)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)


def test_fetch_pdf_returns_text(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _build_pdf(["Line one of the study.", "Line two with more detail." * 30])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, headers={"content-type": "application/pdf"})

    _patch_transport(monkeypatch, httpx.MockTransport(handler))

    text = asyncio.run(fetch_pdf("https://example.com/paper.pdf", min_chars=50, timeout_seconds=5.0))
    assert "study" in text.lower()


def test_fetch_pdf_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"oops")

    _patch_transport(monkeypatch, httpx.MockTransport(handler))

    with pytest.raises(FetcherError):
        asyncio.run(fetch_pdf("https://example.com/paper.pdf", min_chars=10, timeout_seconds=5.0))
