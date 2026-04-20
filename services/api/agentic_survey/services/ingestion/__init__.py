"""Ingestion pipeline for M2.

``knowledge_source`` rows in ``queued`` state walk through the linear state
machine ``fetching → extracting → chunking → embedding → pending_approval``
via :func:`process_source`. Scientists approve the pending rows through the
existing knowledge rail. The pipeline never auto-approves.

Fetchers are tiered. Tier-1 uses ``httpx + readability-lxml`` for HTML and
``pypdf`` for PDFs. When tier-1 returns insufficient content the pipeline
escalates to ``crawl4ai`` if ``SURVEY_INGEST_CRAWL4AI`` is enabled and the
package is installed.
"""

from agentic_survey.services.ingestion.pipeline import (
    IngestionError,
    SourceNotFetchable,
    Tier1Insufficient,
    process_source,
    run_forever,
    run_once,
)

__all__ = [
    "IngestionError",
    "SourceNotFetchable",
    "Tier1Insufficient",
    "process_source",
    "run_forever",
    "run_once",
]
