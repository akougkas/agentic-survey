"""Runtime vocabulary for admin surfaces; bundles select a subset."""

from __future__ import annotations

from typing import Final

ADMIN_SURFACES: Final[tuple[str, ...]] = (
    "catalog",
    "campaigns",
    "sessions",
    "transcripts",
    "answers",
    "invites",
    "designer",
    "knowledge",
    "graph",
    "models",
    "bundle",
)


def is_known_surface(key: str) -> bool:
    return key in ADMIN_SURFACES
