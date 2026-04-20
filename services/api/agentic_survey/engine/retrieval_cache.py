from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field
from threading import RLock

__all__ = ["RetrievalCache", "RetrievalCacheEntry"]

_DEFAULT_TTL_SECONDS = 600.0  # 10 minutes per design §4.4
_RECENT_ENTRIES = 3
_WORD_RE = re.compile(r"[a-zA-Z0-9]+")


@dataclass(slots=True, frozen=True)
class RetrievalCacheEntry:
    query: str
    chunk_ids: tuple[str, ...]
    scores: tuple[float, ...]
    created_at: float


@dataclass(slots=True)
class _SessionBucket:
    entries: deque[RetrievalCacheEntry] = field(default_factory=lambda: deque(maxlen=_RECENT_ENTRIES))


class RetrievalCache:
    """Per-session short-term cache for Brain B retrieval results.

    Each session tracks the most recent ``_RECENT_ENTRIES`` queries. ``get``
    returns one or more cached entries whose normalized-query edit distance
    to the lookup falls within ``edit_distance_tolerance`` (default 2). The
    cache exists so Brain B can reuse the same chunks across clarifying
    turns without re-hitting SurrealDB. TTL is 10 minutes from creation.
    """

    def __init__(self, *, ttl_seconds: float = _DEFAULT_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._buckets: dict[str, _SessionBucket] = {}
        self._lock = RLock()

    def put(
        self,
        session_id: str,
        query: str,
        chunk_ids: list[str],
        scores: list[float],
    ) -> None:
        entry = RetrievalCacheEntry(
            query=query,
            chunk_ids=tuple(chunk_ids),
            scores=tuple(scores),
            created_at=time.monotonic(),
        )
        with self._lock:
            bucket = self._buckets.setdefault(session_id, _SessionBucket())
            bucket.entries.append(entry)

    def get(
        self,
        session_id: str,
        query: str,
        edit_distance_tolerance: int = 2,
    ) -> list[RetrievalCacheEntry] | None:
        with self._lock:
            bucket = self._buckets.get(session_id)
            if bucket is None:
                return None
            fresh: deque[RetrievalCacheEntry] = deque(maxlen=_RECENT_ENTRIES)
            now = time.monotonic()
            for entry in bucket.entries:
                if now - entry.created_at <= self._ttl_seconds:
                    fresh.append(entry)
            bucket.entries = fresh
            if not fresh:
                self._buckets.pop(session_id, None)
                return None

            normalized_query = _normalize(query)
            matches = [
                entry
                for entry in fresh
                if _edit_distance(normalized_query, _normalize(entry.query)) <= edit_distance_tolerance
            ]
            return matches or None

    def invalidate(self, session_id: str) -> None:
        with self._lock:
            self._buckets.pop(session_id, None)


def _normalize(text: str) -> str:
    return " ".join(token.lower() for token in _WORD_RE.findall(text))


def _edit_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, lc in enumerate(left, start=1):
        current = [i] + [0] * len(right)
        for j, rc in enumerate(right, start=1):
            cost = 0 if lc == rc else 1
            current[j] = min(
                current[j - 1] + 1,
                previous[j] + 1,
                previous[j - 1] + cost,
            )
        previous = current
    return previous[-1]
