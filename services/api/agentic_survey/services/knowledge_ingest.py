from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from agentic_survey.bundles import SeedSource
from agentic_survey.tools.chunker import chunk_text

logger = logging.getLogger(__name__)

__all__ = [
    "IngestResult",
    "ingest_seed_sources",
]


@dataclass(slots=True)
class IngestResult:
    created_source_ids: list[str]
    created_chunk_count: int
    skipped: list[str]


def _hash_content(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def ingest_seed_sources(
    campaign_id: str,
    sources: list[SeedSource],
    repository,
) -> IngestResult:
    """Persist bundle seed_sources as knowledge_source rows.

    ``raw_text`` seeds are chunked synchronously and land as
    ``pending_approval`` so the scientist can approve them before the
    campaign goes live. ``url`` and ``pdf`` seeds land as ``kind=url|pdf``
    with ``status=queued``; the M2 ingestion worker picks them up and
    walks them through ``fetching → extracting → chunking → embedding →
    pending_approval``. Ingestion never aborts campaign creation; per-seed
    failures are logged and appended to ``skipped``.
    """
    created_source_ids: list[str] = []
    created_chunk_count = 0
    skipped: list[str] = []

    for seed in sources:
        try:
            if seed.kind == "raw_text":
                content = (seed.content_inline or "").strip()
                if not content:
                    skipped.append(f"{seed.title}: raw_text with empty content_inline")
                    continue
                source = repository.create_knowledge_source(
                    campaign_id=campaign_id,
                    kind="bundle_seed",
                    title=seed.title,
                    hash_value=_hash_content(content),
                    rationale=seed.rationale,
                    status="pending_approval",
                )
                spans = chunk_text(content)
                for index, span in enumerate(spans):
                    repository.create_knowledge_chunk(
                        campaign_id=campaign_id,
                        source_id=source.id,
                        content=span.content,
                        position=index,
                        char_start=span.start_char,
                        char_end=span.end_char,
                        approved=False,
                    )
                created_source_ids.append(source.id)
                created_chunk_count += len(spans)
            elif seed.kind in {"url", "pdf"}:
                if not seed.url:
                    skipped.append(f"{seed.title}: {seed.kind} seed missing url")
                    continue
                source = repository.create_knowledge_source(
                    campaign_id=campaign_id,
                    kind=seed.kind,
                    title=seed.title,
                    hash_value=_hash_content(seed.url),
                    url=seed.url,
                    rationale=seed.rationale,
                    status="queued",
                )
                created_source_ids.append(source.id)
            else:
                skipped.append(f"{seed.title}: unsupported kind={seed.kind}")
        except Exception as exc:
            logger.exception("seed_source ingestion failed", extra={"title": seed.title})
            skipped.append(f"{seed.title}: {exc}")

    return IngestResult(
        created_source_ids=created_source_ids,
        created_chunk_count=created_chunk_count,
        skipped=skipped,
    )
