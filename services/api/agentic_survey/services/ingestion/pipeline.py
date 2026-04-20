from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

from agentic_survey.services.ingestion.embed import EmbeddingError, embed_chunks
from agentic_survey.services.ingestion.fetchers.http import (
    FetcherError,
    Tier1Insufficient,
    fetch_html,
)
from agentic_survey.services.ingestion.fetchers.pdf import fetch_pdf
from agentic_survey.tools.chunker import chunk_text

logger = logging.getLogger(__name__)

__all__ = [
    "IngestionError",
    "SourceNotFetchable",
    "Tier1Insufficient",
    "process_source",
    "run_forever",
    "run_once",
]


class IngestionError(RuntimeError):
    """Raised when a source cannot complete the pipeline.

    The pipeline always marks the source ``failed`` with ``error_detail``
    populated before re-raising, so callers can tail the audit.
    """


class SourceNotFetchable(IngestionError):
    """Worker received a source with a kind it does not handle (e.g. raw_text).

    ``raw_text`` seeds are chunked synchronously by
    ``services/knowledge_ingest.py`` and never hit the worker. Bundle
    seeds should never land in ``queued`` status for ``raw_text``.
    """


# Public "how far did we get" progress hook for tests + UI.
OnProgress = Optional[Callable[[str, str], Awaitable[None] | None]]


async def process_source(
    *,
    source_id: str,
    repository: Any,
    router: Any,
    settings: Any | None = None,
    on_progress: OnProgress = None,
) -> None:
    """Walk a single ``knowledge_source`` through the ingestion state machine.

    Idempotent: callers can safely invoke twice; only ``queued`` sources
    advance. On any failure the source is marked ``failed`` with
    ``error_detail`` populated and the exception is re-raised.
    """
    cfg = settings if settings is not None else _load_settings()

    source = repository.get_knowledge_source(source_id)
    if source is None:
        raise IngestionError(f"knowledge_source {source_id} not found")
    if source.status != "queued":
        logger.info(
            "skipping source id=%s kind=%s status=%s",
            source_id,
            source.kind,
            source.status,
        )
        return

    logger.info("ingesting source id=%s kind=%s url=%s", source_id, source.kind, source.url)
    await _emit_progress(on_progress, source_id, "queued")

    try:
        await _advance(repository, source_id, "fetching", on_progress)
        extracted = await _fetch(source, cfg, repository, on_progress)

        await _advance(repository, source_id, "extracting", on_progress)
        if len(extracted) < cfg.ingest_min_chars:
            raise Tier1Insufficient(
                f"extracted body below min_chars={cfg.ingest_min_chars} ({len(extracted)} chars)"
            )

        await _advance(repository, source_id, "chunking", on_progress)
        chunks = chunk_text(extracted)
        if not chunks:
            raise IngestionError("chunker returned zero spans")
        created = []
        for index, span in enumerate(chunks):
            record = repository.create_knowledge_chunk(
                campaign_id=source.campaign_id,
                source_id=source.id,
                content=span.content,
                position=index,
                char_start=span.start_char,
                char_end=span.end_char,
                approved=False,
            )
            created.append(record)

        await _advance(repository, source_id, "embedding", on_progress)
        vectors = await embed_chunks(
            [c.content for c in created],
            router=router,
        )
        for chunk, vec in zip(created, vectors):
            repository.update_knowledge_chunk_embedding(chunk.id, vec)

        repository.update_knowledge_source_status(
            source_id,
            status="pending_approval",
            error_detail="",  # "" clears any prior tier-1-insufficient note.
        )
        await _emit_progress(on_progress, source_id, "pending_approval")
        logger.info(
            "ingested source id=%s chars=%d chunks=%d",
            source_id,
            len(extracted),
            len(created),
        )
    except Exception as exc:
        detail = _truncate(str(exc), 1024)
        logger.exception("ingestion failed source_id=%s", source_id)
        try:
            repository.update_knowledge_source_status(
                source_id,
                status="failed",
                error_detail=detail,
            )
        except Exception:
            logger.exception(
                "failed to mark source_id=%s as failed after error", source_id
            )
        raise


async def run_once(
    *,
    repository: Any,
    router: Any,
    settings: Any | None = None,
    limit: int = 32,
) -> int:
    """Pick up to ``limit`` queued sources and run them through the pipeline.

    Returns the count of sources that finished in ``pending_approval``. A
    failure on one source does not block the rest; each is retried on the
    next tick.
    """
    cfg = settings if settings is not None else _load_settings()
    queued = list(repository.list_knowledge_sources_by_status(["queued"]))[:limit]
    if not queued:
        return 0

    logger.info("ingest tick: %d queued source(s)", len(queued))
    completed = 0
    for source in queued:
        try:
            await process_source(
                source_id=source.id,
                repository=repository,
                router=router,
                settings=cfg,
            )
            completed += 1
        except Exception:
            logger.exception("process_source error for %s", source.id)
    return completed


async def run_forever(
    *,
    repository: Any,
    router: Any,
    settings: Any | None = None,
) -> None:
    """Long-running worker loop for ``python -m agentic_survey.tools.freshness``.

    Polls the repository every ``SURVEY_FRESHNESS_POLL_SECONDS``; each tick
    is short so new rows start within one poll period. Exits on
    ``KeyboardInterrupt``.
    """
    cfg = settings if settings is not None else _load_settings()
    poll = max(1, int(getattr(cfg, "freshness_poll_seconds", 30)))
    max_backoff = max(poll * 8, poll)
    consecutive_failures = 0
    logger.info("freshness worker starting; poll=%ds", poll)
    while True:
        try:
            await run_once(repository=repository, router=router, settings=cfg)
            consecutive_failures = 0
            sleep_for = poll
        except Exception:
            consecutive_failures += 1
            sleep_for = min(poll * (2 ** (consecutive_failures - 1)), max_backoff)
            logger.exception(
                "run_once crashed; backoff=%ds (consecutive_failures=%d)",
                sleep_for,
                consecutive_failures,
            )
        await asyncio.sleep(sleep_for)


async def _fetch(
    source: Any,
    settings: Any,
    repository: Any,
    on_progress: OnProgress,
) -> str:
    """Fetch source content with tier-1 / tier-2 dispatch."""
    url = source.url
    if not url:
        raise SourceNotFetchable(f"source kind={source.kind!r} has no url")

    if source.kind == "pdf":
        return await fetch_pdf(
            url,
            min_chars=settings.ingest_min_chars,
            timeout_seconds=settings.ingest_http_timeout_seconds,
        )

    if source.kind == "url":
        try:
            return await fetch_html(
                url,
                min_chars=settings.ingest_min_chars,
                timeout_seconds=settings.ingest_http_timeout_seconds,
            )
        except Tier1Insufficient as exc:
            if not settings.ingest_crawl4ai:
                raise
            logger.info("tier-1 insufficient for %s, escalating to crawl4ai", url)
            try:
                # Note survives through ``extracting → chunking → embedding``
                # because the repository preserves ``error_detail`` when
                # callers omit it; it is cleared on the final
                # ``pending_approval`` transition.
                repository.update_knowledge_source_status(
                    source.id,
                    status="fetching",
                    error_detail=f"tier1 insufficient: {exc}",
                )
            except Exception:
                # Non-blocking: the escalation note is observability only.
                logger.exception("failed to write tier1 escalation note")
            await _emit_progress(on_progress, source.id, "escalating")
            from agentic_survey.services.ingestion.fetchers.crawl4ai import (
                fetch_with_crawl4ai,
            )
            return await fetch_with_crawl4ai(
                url,
                min_chars=settings.ingest_min_chars,
                timeout_seconds=settings.ingest_crawl4ai_timeout_seconds,
            )

    raise SourceNotFetchable(f"kind={source.kind!r} is not fetchable by the worker")


async def _advance(
    repository: Any,
    source_id: str,
    status: str,
    on_progress: OnProgress,
) -> None:
    """Advance a source to the next intermediate state.

    ``error_detail`` is intentionally omitted so the repository preserves
    any prior note (e.g. the tier-1-insufficient escalation marker written
    inside ``_fetch``). The pipeline explicitly clears the note at
    ``pending_approval`` and replaces it with a new value on ``failed``.
    """
    repository.update_knowledge_source_status(source_id, status=status)
    await _emit_progress(on_progress, source_id, status)


async def _emit_progress(
    on_progress: OnProgress, source_id: str, status: str
) -> None:
    if on_progress is None:
        return
    result = on_progress(source_id, status)
    if asyncio.iscoroutine(result):
        await result


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _load_settings() -> Any:
    from agentic_survey.config import get_settings

    return get_settings()
