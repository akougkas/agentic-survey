"""Hybrid retrieval entry point (BM25 + vector + RRF).

One async function, ``search_knowledge``, is the single retrieval entry
for every Brain-B tool call. Three modes:

- ``bm25``   — BM25 only. Exact-keyword recall path.
- ``vector`` — Cosine KNN over embeddings. Semantic path.
- ``hybrid`` — Both, fused by Reciprocal Rank Fusion. Default.

Every call writes exactly one ``retrieval_audit`` row, carrying ``mode``
and ``cache_hit`` so the admin audit drawer can confirm which path the
runtime chose. On cache hit we still record the chunk ids so the turn
drawer looks identical in either case.
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable, Literal

from agentic_survey.engine.retrieval_cache import RetrievalCache, RetrievalCacheEntry
from agentic_survey.repository import ChunkHit
from agentic_survey.services.retrieval_embed import RetrievalError, embed_query
from agentic_survey.services.retrieval_fusion import rrf_fuse

__all__ = [
    "RetrievalError",
    "SearchKnowledgeFn",
    "build_search_knowledge",
    "search_knowledge",
]

Surface = Literal["designer", "interviewer"]
Mode = Literal["bm25", "vector", "hybrid"]
SearchKnowledgeFn = Callable[..., "Any"]


async def search_knowledge(
    *,
    campaign_id: str,
    query: str,
    k: int,
    mode: Mode,
    repository,
    surface: Surface,
    router=None,
    session_id: str | None = None,
    cache: RetrievalCache | None = None,
) -> list[ChunkHit]:
    """Run retrieval in the requested ``mode`` and audit the call.

    Results are filtered to ``approved=true`` chunks only. Cache lookups
    are scoped to ``(session_id, query, mode)``; a hit skips BM25, query
    embedding, and vector search, and still writes an audit row with
    ``cache_hit=true``.
    """
    cleaned = (query or "").strip()
    if not cleaned:
        return []
    if k <= 0:
        return []
    if mode not in ("bm25", "vector", "hybrid"):
        raise ValueError(f"unknown retrieval mode: {mode!r}")

    # ---- 1. cache lookup (only if session-scoped) --------------------
    cached_hits = _cache_lookup(cache, session_id, cleaned, mode, repository=repository)
    if cached_hits is not None:
        _write_audit(
            repository,
            campaign_id=campaign_id,
            surface=surface,
            query=cleaned,
            k=k,
            hits=cached_hits,
            mode=mode,
            cache_hit=True,
        )
        return cached_hits

    # ---- 2. cold path: run the requested mode ------------------------
    if mode == "bm25":
        fused = _run_bm25(repository, campaign_id=campaign_id, query=cleaned, k=k)
        vec_hash = ""
    elif mode == "vector":
        if router is None:
            raise RetrievalError("vector mode requires a router for embedding the query")
        vector = await embed_query(cleaned, router=router)
        vec_hash = _hash_vector(vector)
        fused = repository.search_knowledge_chunks_vector(
            campaign_id=campaign_id, vector=vector, k=k
        )
    else:
        # hybrid: BM25 + vector, then RRF. Pull k*2 vector candidates so
        # RRF has meaningful head competition against the BM25 top-k.
        bm25_hits = _run_bm25(repository, campaign_id=campaign_id, query=cleaned, k=k)
        if router is None:
            raise RetrievalError("hybrid mode requires a router for embedding the query")
        vector = await embed_query(cleaned, router=router)
        vec_hash = _hash_vector(vector)
        vector_hits = repository.search_knowledge_chunks_vector(
            campaign_id=campaign_id, vector=vector, k=max(k * 2, 1)
        )
        fused = rrf_fuse(bm25_hits, vector_hits, k=k)

    # ---- 3. cache write + audit -------------------------------------
    if cache is not None and session_id:
        cache.put(
            session_id,
            cleaned,
            [hit.chunk_id for hit in fused],
            [hit.score for hit in fused],
            mode=mode,
            query_vec_hash=vec_hash,
        )
    _write_audit(
        repository,
        campaign_id=campaign_id,
        surface=surface,
        query=cleaned,
        k=k,
        hits=fused,
        mode=mode,
        cache_hit=False,
    )
    return fused


def build_search_knowledge(
    *,
    repository,
    campaign_id: str,
    surface: Surface,
    router=None,
    session_id: str | None = None,
    cache: RetrievalCache | None = None,
    default_mode: Mode = "hybrid",
) -> SearchKnowledgeFn:
    """Bind a ``search_knowledge(query, k, mode=None)`` callable Brain B can call.

    The binding captures the repository, campaign, surface, router, and
    per-session cache so Brain B only has to pass the query, top-k, and
    optionally a mode override. ``default_mode`` is ``"hybrid"``; callers
    that want to force a BM25-only surface (e.g. a diagnostic tool) can
    override it.

    When the operator sets ``SURVEY_RETRIEVAL_FORCE_MODE`` to a valid mode
    name, that value overrides whatever the caller (typically Brain B)
    requests. This is the operator backstop for outages where the
    embedding endpoint is unreachable; setting force_mode=bm25 keeps the
    retrieval surface working without touching prompts or code.
    """
    from agentic_survey.config import get_settings

    forced = get_settings().retrieval_force_mode.strip().lower()
    forced_mode: Mode | None = forced if forced in ("bm25", "vector", "hybrid") else None  # type: ignore[assignment]

    async def _bound(
        query: str,
        k: int,
        mode: str | None = None,
    ) -> list[dict[str, Any]]:
        resolved = forced_mode or mode or default_mode
        hits = await search_knowledge(
            campaign_id=campaign_id,
            query=query,
            k=k,
            mode=resolved,  # type: ignore[arg-type]
            repository=repository,
            surface=surface,
            router=router,
            session_id=session_id,
            cache=cache,
        )
        return [hit.model_dump() for hit in hits]

    return _bound


# ---------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------


def _run_bm25(repository, *, campaign_id: str, query: str, k: int) -> list[ChunkHit]:
    return list(
        repository.search_knowledge_chunks_bm25(
            campaign_id=campaign_id, query=query, k=k
        )
    )


def _cache_lookup(
    cache: RetrievalCache | None,
    session_id: str | None,
    query: str,
    mode: str,
    *,
    repository,
) -> list[ChunkHit] | None:
    """Serve a cached result if one matches, else ``None``.

    The cache is only consulted when a session id is present; design-time
    Brain B turns skip the cache entirely so the Scientist always sees a
    fresh retrieval. On a hit we rehydrate each cached chunk id through
    ``repository.get_knowledge_chunk`` so Brain B receives the same
    ``ChunkHit`` shape (with real content and source metadata) it would
    get on a cold call. The cache itself stores only ids + scores so the
    query vector never rides in memory across turns (plan §M4).
    """
    if cache is None or not session_id:
        return None
    entries = cache.get(session_id, query, mode=mode)
    if not entries:
        return None
    # Prefer the freshest matching entry (the cache returns newest-last).
    entry = entries[-1]
    hits: list[ChunkHit] = []
    for chunk_id, score in zip(entry.chunk_ids, entry.scores):
        chunk = repository.get_knowledge_chunk(chunk_id)
        if chunk is None:
            # The chunk was removed (rejected / retired) since the cache
            # entry was written. Skip it; Brain B sees a short list rather
            # than a dangling id.
            continue
        source = repository.get_knowledge_source(chunk.source_id)
        hits.append(
            ChunkHit(
                chunk_id=chunk.id,
                content=chunk.content,
                source_id=chunk.source_id,
                source_title=source.title if source is not None else "",
                score=score,
                start_char=chunk.char_start,
                end_char=chunk.char_end,
            )
        )
    return hits


def _write_audit(
    repository,
    *,
    campaign_id: str,
    surface: Surface,
    query: str,
    k: int,
    hits: list[ChunkHit],
    mode: str,
    cache_hit: bool,
) -> None:
    """Write the per-call audit row.

    Invariant: exactly one audit row per ``search_knowledge`` call. We do
    not swallow failures here; a silent audit failure would mean the
    admin drawer shows no record of what Mira saw, with no visible
    signal that anything is wrong. The route propagates the error.
    """
    repository.record_retrieval_audit(
        campaign_id=campaign_id,
        surface=surface,
        query=query,
        top_k=k,
        chunk_ids=[hit.chunk_id for hit in hits],
        scores=[hit.score for hit in hits],
        mode=mode,
        cache_hit=cache_hit,
    )


def _hash_vector(vector: list[float]) -> str:
    """Stable short digest of a query vector for cache provenance."""
    hasher = hashlib.sha1()
    for value in vector:
        hasher.update(f"{value:.6f}".encode("ascii"))
    return hasher.hexdigest()[:16]
