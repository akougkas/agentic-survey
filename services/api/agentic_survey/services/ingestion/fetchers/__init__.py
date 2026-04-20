"""Content fetchers for the ingestion pipeline.

Tier-1 (always available): ``http.fetch_html`` and ``pdf.fetch_pdf``.
Tier-2 (lazy): ``crawl4ai.fetch_with_crawl4ai`` is imported on demand.
"""

from agentic_survey.services.ingestion.fetchers.http import fetch_html
from agentic_survey.services.ingestion.fetchers.pdf import fetch_pdf

__all__ = ["fetch_html", "fetch_pdf"]
