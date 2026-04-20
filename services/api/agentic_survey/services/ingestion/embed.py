from __future__ import annotations

import logging
from typing import Any, Sequence

logger = logging.getLogger(__name__)

__all__ = ["EmbeddingError", "embed_chunks"]

_DEFAULT_BATCH = 16
_EXPECTED_DIM = 768


class EmbeddingError(RuntimeError):
    """Raised when the embeddings model refuses a batch or returns garbage.

    Invariant-per-project: no silent fallback. The pipeline catches this
    and marks the source ``failed`` with ``error_detail`` populated.
    """


async def embed_chunks(
    texts: Sequence[str],
    *,
    router: Any,
    model: str = "embeddings",
    batch_size: int = _DEFAULT_BATCH,
    expected_dim: int = _EXPECTED_DIM,
) -> list[list[float]]:
    """Embed ``texts`` via the LiteLLM router's ``aembedding``.

    Calls the model in batches of ``batch_size`` (default 16 so the prompt
    window for Nomic Embed Text v2 MoE is never exceeded). Returns one
    ``list[float]`` per input, in the same order. Raises
    :class:`EmbeddingError` on any malformed response; never pads with
    zeros or returns an empty list.
    """
    if router is None:
        raise EmbeddingError("router is None")
    if batch_size <= 0:
        raise EmbeddingError("batch_size must be > 0")

    items = list(texts)
    if not items:
        return []

    vectors: list[list[float]] = []
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        try:
            response = await router.aembedding(model=model, input=batch)
        except Exception as exc:
            raise EmbeddingError(
                f"aembedding batch {start}-{start + len(batch)} failed: {exc}"
            ) from exc
        batch_vectors = _extract_vectors(response, expected_count=len(batch))
        _validate_dim(batch_vectors, expected=expected_dim)
        vectors.extend(batch_vectors)

    if len(vectors) != len(items):
        raise EmbeddingError(
            f"expected {len(items)} embeddings, got {len(vectors)}"
        )
    return vectors


def _extract_vectors(response: Any, *, expected_count: int) -> list[list[float]]:
    """Unwrap LiteLLM / OpenAI-style embedding responses.

    Accepts dicts (raw OpenAI) or Pydantic-ish objects (LiteLLM's
    ``EmbeddingResponse``). Each data entry exposes an ``embedding`` list.
    """
    data: Any = None
    if isinstance(response, dict):
        data = response.get("data")
    else:
        data = getattr(response, "data", None)

    if data is None:
        raise EmbeddingError(f"embedding response missing 'data': {response!r}")

    vectors: list[list[float]] = []
    for entry in data:
        if isinstance(entry, dict):
            vec = entry.get("embedding")
        else:
            vec = getattr(entry, "embedding", None)
        if vec is None:
            raise EmbeddingError(f"embedding entry missing 'embedding': {entry!r}")
        coerced = [float(x) for x in vec]
        if not coerced:
            raise EmbeddingError("embedding vector is empty")
        vectors.append(coerced)

    if len(vectors) != expected_count:
        raise EmbeddingError(
            f"expected {expected_count} embeddings in batch, got {len(vectors)}"
        )
    return vectors


def _validate_dim(vectors: list[list[float]], *, expected: int) -> None:
    for vec in vectors:
        if len(vec) != expected:
            raise EmbeddingError(
                f"embedding dimension mismatch: expected {expected}, got {len(vec)}"
            )
