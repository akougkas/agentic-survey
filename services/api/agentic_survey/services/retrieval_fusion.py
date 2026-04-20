"""Reciprocal Rank Fusion for hybrid BM25 + vector retrieval.

Pure, dependency-free helper used by ``services/retrieval.py``. The M4
invariant is rank-based fusion so BM25's negative log-likelihood scores
and cosine-similarity floats never land in the same arithmetic.
"""

from __future__ import annotations

from typing import Iterable

from agentic_survey.repository import ChunkHit

__all__ = ["RRF_K", "rrf_fuse"]


# RRF smoothing constant. The original paper uses 60; it damps the head of
# each ranked list so rank-1 agreements are not overwhelmingly dominant.
RRF_K = 60


def rrf_fuse(
    bm25_hits: Iterable[ChunkHit],
    vector_hits: Iterable[ChunkHit],
    *,
    k: int,
    k_const: int = RRF_K,
) -> list[ChunkHit]:
    """Fuse two ordered lists of ``ChunkHit`` via Reciprocal Rank Fusion.

    Each chunk's fused score is ``sum(1 / (k_const + rank))`` across the
    lists in which it appears, using 1-based ranks. Ties break by the
    lowest best-rank across the two inputs (deterministic). Returns at
    most ``k`` hits; the per-chunk content / source fields come from the
    earlier-ranked source list for that chunk.

    ``bm25_hits`` and ``vector_hits`` may be any iterables but each must
    already be ordered best-first by its own ranker. Scores on the inputs
    are ignored; only the rank position matters.
    """
    if k <= 0:
        return []
    if k_const <= 0:
        raise ValueError(f"k_const must be positive, got {k_const}")

    bm25_list = list(bm25_hits)
    vector_list = list(vector_hits)

    fused_scores: dict[str, float] = {}
    best_ranks: dict[str, int] = {}
    representatives: dict[str, ChunkHit] = {}

    def _accumulate(hits: list[ChunkHit]) -> None:
        for index, hit in enumerate(hits):
            rank = index + 1  # 1-based rank per the RRF paper
            contribution = 1.0 / (k_const + rank)
            chunk_id = hit.chunk_id
            fused_scores[chunk_id] = fused_scores.get(chunk_id, 0.0) + contribution
            prior_best = best_ranks.get(chunk_id)
            if prior_best is None or rank < prior_best:
                best_ranks[chunk_id] = rank
                representatives[chunk_id] = hit

    _accumulate(bm25_list)
    _accumulate(vector_list)

    if not fused_scores:
        return []

    ordered_ids = sorted(
        fused_scores.keys(),
        key=lambda cid: (-fused_scores[cid], best_ranks[cid], cid),
    )

    fused: list[ChunkHit] = []
    for chunk_id in ordered_ids[:k]:
        rep = representatives[chunk_id]
        fused.append(rep.model_copy(update={"score": fused_scores[chunk_id]}))
    return fused
