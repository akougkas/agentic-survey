"""Knowledge-graph read closures used by the Brain-B ``get_graph_neighborhood`` tool.

Mirrors the ``build_search_knowledge`` closure pattern in
``services/retrieval.py``: bind a repository + campaign id and return an
awaitable that Brain B's tool handler can call with just the
participant-facing arguments.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

__all__ = ["NeighborhoodFn", "build_neighborhood_provider"]

NeighborhoodFn = Callable[..., Awaitable[dict[str, Any]]]


def build_neighborhood_provider(
    *,
    repository,
    campaign_id: str,
) -> NeighborhoodFn:
    """Bind a ``neighborhood(label, k, depth)`` callable for Brain B.

    The repository call is synchronous, but the tool-registry handler
    signature is async so we adapt. Failures propagate unchanged; the
    caller's orchestrator captures them as a tool-role error message.
    """

    async def _bound(label: str, k: int = 8, depth: int = 1) -> dict[str, Any]:
        return repository.list_concept_neighborhood(
            campaign_id=campaign_id,
            label=label,
            k=k,
            depth=depth,
        )

    return _bound
