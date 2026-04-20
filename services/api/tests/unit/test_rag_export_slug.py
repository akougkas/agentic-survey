"""Slug resolution for ``./campaigns/{slug}/rag/`` is deterministic.

A slug must collapse whitespace, lowercase, and drop anything outside
``[a-z0-9-]``. When two campaigns collide on the same base slug, the
second one's path gets ``{slug}-{short_id}`` appended so they land in
their own directories.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from agentic_survey.repository import InMemoryRepository
from agentic_survey.services.rag_export.writer import (
    _resolve_slug,
    slugify_campaign_title,
    sync_campaign_rag_folder,
)


def test_slugify_basic_lowercase_with_em_dash() -> None:
    # ``CITADEL — Pilot 1`` — the em-dash is outside [a-z0-9-] and is
    # dropped; whitespace collapses to a single dash.
    assert slugify_campaign_title("CITADEL — Pilot 1") == "citadel-pilot-1"


def test_slugify_collapses_runs_of_dashes() -> None:
    assert slugify_campaign_title("  hello   world  ") == "hello-world"
    assert slugify_campaign_title("a // b // c") == "a-b-c"


def test_slugify_returns_empty_for_all_unicode() -> None:
    # ``中文`` has no latin alphanumerics; writer falls back to the
    # short campaign id.
    assert slugify_campaign_title("中文") == ""


def test_resolve_slug_without_collision_uses_base() -> None:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Thematic Study", min_n=3, max_n=6)
    assert _resolve_slug(repo, campaign) == "thematic-study"


def test_resolve_slug_collision_appends_short_id_to_second_campaign() -> None:
    repo = InMemoryRepository()
    first = repo.create_campaign(title="Thematic Study", min_n=3, max_n=6)
    second = repo.create_campaign(title="Thematic Study", min_n=3, max_n=6)

    first_slug = _resolve_slug(repo, first)
    second_slug = _resolve_slug(repo, second)

    assert first_slug == "thematic-study"
    assert second_slug.startswith("thematic-study-")
    assert second_slug != first_slug
    # Deterministic: the short id comes from the second campaign's uuid,
    # so re-resolving must return the same slug.
    assert _resolve_slug(repo, second) == second_slug


def test_sync_uses_slug_override_when_provided(tmp_path: Path) -> None:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Anything", min_n=3, max_n=6)

    rag_dir = asyncio.run(
        sync_campaign_rag_folder(
            campaign_id=campaign.id,
            repository=repo,
            root=tmp_path,
            slug_override="pinned-slug",
        )
    )
    assert rag_dir == (tmp_path / "pinned-slug" / "rag").resolve()
    assert rag_dir.is_dir()


def test_sync_degenerate_title_falls_back_to_short_id(tmp_path: Path) -> None:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="中文", min_n=3, max_n=6)

    rag_dir = asyncio.run(
        sync_campaign_rag_folder(
            campaign_id=campaign.id,
            repository=repo,
            root=tmp_path,
        )
    )
    # The short-id fallback is a lowercase hex prefix of the uuid tail.
    slug = rag_dir.parent.name
    assert slug != ""
    assert slug.replace("-", "").isalnum()
