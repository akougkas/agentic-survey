from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(slots=True, frozen=True)
class WebSearchResult:
    """One search hit returned by any ``WebSearchBackend``.

    ``source`` names the backend that produced the row (e.g. ``"searxng"``,
    ``"ddg"``) so the audit trail can tell which fallback fired. Callers
    should treat every field as untrusted user-adjacent text and strip /
    truncate before persisting.
    """

    title: str
    url: str
    snippet: str
    source: str


@runtime_checkable
class WebSearchBackend(Protocol):
    """Minimal async search backend contract.

    Implementations raise on network or parse failure so the router can
    fall back to the next backend. Returning an empty list is a successful
    no-hit and does NOT trigger fallback.
    """

    name: str

    async def search(
        self,
        query: str,
        top_k: int,
    ) -> list[WebSearchResult]: ...
