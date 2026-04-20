"""Unit tests for ``embed_query``.

Reuses the M2 router mock shapes (``_GoodRouter`` / ``_ShortVectorRouter``)
because ``embed_query`` is the query-side analog of ``embed_chunks`` and
must reject the same failure modes.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agentic_survey.services.retrieval_embed import RetrievalError, embed_query


class _GoodRouter:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        self.calls.append(list(input))
        return {"data": [{"embedding": [0.01] * 768} for _ in input]}


class _ShortVectorRouter:
    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        return {"data": [{"embedding": [0.1] * 512}]}


class _EmptyDataRouter:
    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        return {"data": []}


class _BoomRouter:
    async def aembedding(self, *, model: str, input: list[str]) -> dict[str, Any]:
        raise RuntimeError("endpoint 503")


def test_embed_query_returns_768_dim_vector() -> None:
    router = _GoodRouter()
    vec = asyncio.run(embed_query("saturation heuristic", router=router))
    assert len(vec) == 768
    # The router saw exactly one input, shape-matching embed_chunks batch-of-1.
    assert router.calls == [["saturation heuristic"]]


def test_embed_query_raises_on_dimension_mismatch() -> None:
    with pytest.raises(RetrievalError) as exc:
        asyncio.run(embed_query("x", router=_ShortVectorRouter()))
    assert "dimension" in str(exc.value)


def test_embed_query_raises_on_empty_data() -> None:
    with pytest.raises(RetrievalError):
        asyncio.run(embed_query("x", router=_EmptyDataRouter()))


def test_embed_query_raises_on_router_exception() -> None:
    with pytest.raises(RetrievalError) as exc:
        asyncio.run(embed_query("x", router=_BoomRouter()))
    assert "endpoint 503" in str(exc.value)


def test_embed_query_rejects_blank_query() -> None:
    with pytest.raises(RetrievalError):
        asyncio.run(embed_query("   ", router=_GoodRouter()))


def test_embed_query_rejects_none_router() -> None:
    with pytest.raises(RetrievalError):
        asyncio.run(embed_query("x", router=None))
