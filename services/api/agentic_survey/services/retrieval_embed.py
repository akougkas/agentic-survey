"""Query embedding for hybrid retrieval.

One public entry: :func:`embed_query`. Calls the LiteLLM router's
``aembedding`` on the ``embeddings`` model (Nomic v2 MoE on the dynamo
endpoint in production; model id comes from ``SURVEY_EMBEDDING_MODEL``,
never hardcoded here) with a batch of size one. Raises
:class:`RetrievalError` on any failure so the route surfaces a real
error; invariant: no silent fallback.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from agentic_survey.llm.callbacks import failure_callback, success_callback

logger = logging.getLogger(__name__)

__all__ = ["RetrievalError", "embed_query", "EXPECTED_DIM"]


EXPECTED_DIM = 768


class RetrievalError(RuntimeError):
    """Raised when query embedding or vector search cannot proceed.

    The hybrid retrieval path never silently falls back to BM25 on an
    embedding failure. Callers propagate this exception; the route that
    invoked ``search_knowledge`` returns the error to the user.
    """


async def embed_query(
    query: str,
    *,
    router: Any,
    model: str = "embeddings",
    expected_dim: int = EXPECTED_DIM,
    metadata: dict[str, Any] | None = None,
) -> list[float]:
    """Embed a single query string using the embeddings model.

    Mirrors the batch-of-one shape used by M2's ``embed_chunks`` so the
    upstream router cache (if any) can hit across ingestion and
    retrieval paths. Returns a ``list[float]`` of length ``expected_dim``.
    """
    if router is None:
        raise RetrievalError("router is None")
    cleaned = (query or "").strip()
    if not cleaned:
        raise RetrievalError("query must be a non-empty string")

    request = {
        "model": model,
        "input": [cleaned],
        "metadata": metadata or {"surface": "retrieval", "brain": "embedding"},
    }
    start_time = datetime.now(tz=UTC)
    try:
        response = await router.aembedding(model=model, input=[cleaned])
    except Exception as exc:
        failure_callback(request, exc, start_time, datetime.now(tz=UTC))
        raise RetrievalError(f"query embedding call failed: {exc}") from exc
    success_callback(request, response, start_time, datetime.now(tz=UTC))

    vector = _extract_single_vector(response)
    if len(vector) != expected_dim:
        raise RetrievalError(
            f"query embedding dimension mismatch: expected {expected_dim}, got {len(vector)}"
        )
    return vector


def _extract_single_vector(response: Any) -> list[float]:
    if isinstance(response, dict):
        data = response.get("data")
    else:
        data = getattr(response, "data", None)
    if not data:
        raise RetrievalError(f"embedding response missing 'data': {response!r}")
    entry = data[0]
    if isinstance(entry, dict):
        vec = entry.get("embedding")
    else:
        vec = getattr(entry, "embedding", None)
    if vec is None:
        raise RetrievalError(f"embedding entry missing 'embedding': {entry!r}")
    coerced = [float(x) for x in vec]
    if not coerced:
        raise RetrievalError("embedding vector is empty")
    return coerced
