"""Unit tests for the pure RRF helper.

RRF is rank-based, not score-based: raw BM25 scores (negative floats) and
cosine-similarity floats must never participate in the fused score. These
tests build synthetic hand-ranked lists and verify the per-chunk fused
score equals ``sum(1/(k_const + rank))`` with 1-based ranks.
"""

from __future__ import annotations

from agentic_survey.repository import ChunkHit
from agentic_survey.services.retrieval_fusion import RRF_K, rrf_fuse


def _hit(chunk_id: str, score: float = 0.0) -> ChunkHit:
    return ChunkHit(
        chunk_id=chunk_id,
        content=f"content-{chunk_id}",
        source_id="src-1",
        source_title="Source 1",
        score=score,
        start_char=0,
        end_char=10,
    )


def test_rrf_score_matches_reciprocal_rank_formula() -> None:
    bm25 = [_hit("A", -1.0), _hit("B", -2.0)]
    vector = [_hit("B", 0.9), _hit("A", 0.8)]
    fused = rrf_fuse(bm25, vector, k=5)

    # A appears at bm25-rank 1 and vector-rank 2; B at bm25-rank 2 and vector-rank 1.
    expected_a = 1.0 / (RRF_K + 1) + 1.0 / (RRF_K + 2)
    expected_b = 1.0 / (RRF_K + 2) + 1.0 / (RRF_K + 1)

    scores = {hit.chunk_id: hit.score for hit in fused}
    assert scores["A"] == expected_a
    assert scores["B"] == expected_b


def test_rrf_promotes_chunks_appearing_in_both_lists() -> None:
    bm25 = [_hit("A"), _hit("B"), _hit("C")]
    vector = [_hit("C"), _hit("D"), _hit("E")]
    fused = rrf_fuse(bm25, vector, k=5)

    # C shows up as rank 3 in BM25 and rank 1 in vector; its fused score is
    # 1/(60+3) + 1/(60+1). That should beat A (rank 1 BM25 only).
    ids = [hit.chunk_id for hit in fused]
    assert ids[0] == "C"


def test_rrf_rank_based_ignores_raw_scores() -> None:
    # BM25 scores are negative; vector scores are positive. A score-based
    # fusion would shove BM25 hits to the bottom. Rank-based fusion treats
    # them equally: the chunk appearing at rank 1 in both wins regardless.
    bm25 = [_hit("X", score=-5.0), _hit("Y", score=-10.0)]
    vector = [_hit("X", score=0.01), _hit("Y", score=0.001)]
    fused = rrf_fuse(bm25, vector, k=2)
    assert fused[0].chunk_id == "X"
    assert fused[1].chunk_id == "Y"


def test_rrf_unique_in_one_list_still_scored() -> None:
    bm25 = [_hit("A"), _hit("B")]
    vector: list[ChunkHit] = []
    fused = rrf_fuse(bm25, vector, k=5)
    scores = {hit.chunk_id: hit.score for hit in fused}
    assert scores["A"] == 1.0 / (RRF_K + 1)
    assert scores["B"] == 1.0 / (RRF_K + 2)


def test_rrf_caps_output_at_k() -> None:
    bm25 = [_hit(f"chunk-{i}") for i in range(10)]
    vector = [_hit(f"chunk-{i + 100}") for i in range(10)]
    fused = rrf_fuse(bm25, vector, k=3)
    assert len(fused) == 3


def test_rrf_handles_empty_inputs() -> None:
    assert rrf_fuse([], [], k=5) == []


def test_rrf_zero_k_returns_empty() -> None:
    bm25 = [_hit("A")]
    vector = [_hit("A")]
    assert rrf_fuse(bm25, vector, k=0) == []
