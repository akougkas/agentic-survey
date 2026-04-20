"""Cold-start migration run against a fresh SurrealDB namespace.

Purges the test NS, runs every file in ``db/migrations/*.surql`` via the
runner, and asserts every table the migrations define is materialised.
Catches regressions where a migration file lands in source but never
makes it to the schema_migration bootstrap path.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from pathlib import Path

import pytest

from agentic_survey.config import Settings
from agentic_survey.db.migrations.runner import MIGRATIONS_DIR

from .conftest import (
    SURREAL_URL,
    _docker_available,
    _ensure_surreal_running,
    apply_migrations_sync,
    drop_namespace,
)

COLD_NS = "agentic_survey_it_cold"
COLD_DB = "cold"

# Every SCHEMAFULL / RELATION table defined across the migration set.
# Update this list when a migration adds a new table.
EXPECTED_TABLES = {
    "schema_migration",
    "campaign",
    "model_catalog",
    "outline_revision",
    "designer_session",
    "designer_turn",
    "invite",
    "interview_session",
    "interview_turn",
    "validator_result",
    "interview_event",
    "knowledge_blob",
    "knowledge_source",
    "knowledge_chunk",
    "retrieval_audit",
    "concept",
    "theme_cluster",
    "mentioned_with",
    "contradicts",
    "part_of_cluster",
    "llm_call_audit",
    "saturation_snapshot",
    "analyst_report",
    "campaign_export",
}


@pytest.fixture(scope="module")
def cold_settings() -> Generator[Settings, None, None]:
    if not _docker_available():
        pytest.skip("docker unavailable")
    _ensure_surreal_running()
    settings = Settings(
        surreal_url=SURREAL_URL,
        surreal_ns=COLD_NS,
        surreal_db=COLD_DB,
        surreal_user="root",
        surreal_pass="root",
        repository="surreal",
    )
    drop_namespace(settings)
    yield settings
    drop_namespace(settings)


async def _info_for_db(settings: Settings) -> dict:
    from surrealdb import AsyncSurreal

    db = AsyncSurreal(settings.surreal_url)
    try:
        await db.signin(
            {"username": settings.surreal_user, "password": settings.surreal_pass}
        )
        await db.use(settings.surreal_ns, settings.surreal_db)
        info = await db.query("INFO FOR DB;")
    finally:
        close = getattr(db, "close", None)
        if callable(close):
            result = close()
            if result is not None:
                await result
    if isinstance(info, list):
        info = info[0] if info else {}
    assert isinstance(info, dict), f"unexpected INFO shape: {type(info).__name__}"
    return info


def test_migrations_manifest_matches_repository() -> None:
    """Guards the EXPECTED_TABLES list against drift.

    Runs purely against the filesystem so it also catches a forgotten
    migration on a docker-less laptop.
    """
    migration_files = sorted(Path(MIGRATIONS_DIR).glob("*.surql"))
    assert migration_files, "no migration files discovered"
    joined = "\n".join(path.read_text() for path in migration_files)
    discovered: set[str] = set()
    for line in joined.splitlines():
        stripped = line.strip()
        prefix = "DEFINE TABLE IF NOT EXISTS "
        if not stripped.startswith(prefix):
            continue
        rest = stripped[len(prefix):]
        name = rest.split()[0]
        discovered.add(name)
    # schema_migration is created by the runner bootstrap, not a file.
    assert discovered <= EXPECTED_TABLES, f"unexpected tables in migrations: {discovered - EXPECTED_TABLES}"
    missing_from_list = (discovered | {"schema_migration"}) - EXPECTED_TABLES
    assert not missing_from_list, f"EXPECTED_TABLES missing entries: {missing_from_list}"


def test_cold_start_applies_every_migration(cold_settings: Settings) -> None:
    apply_migrations_sync(cold_settings)
    info = asyncio.run(_info_for_db(cold_settings))
    tables = info.get("tables") or {}
    assert isinstance(tables, dict), f"INFO.tables not a dict: {type(tables).__name__}"
    missing = EXPECTED_TABLES - set(tables.keys())
    assert not missing, f"migrations did not create tables: {sorted(missing)}"


def test_cold_start_is_idempotent(cold_settings: Settings) -> None:
    """Second run applies nothing new and leaves schema intact."""
    apply_migrations_sync(cold_settings)
    apply_migrations_sync(cold_settings)

    async def _count_applied() -> int:
        from agentic_survey.db.surreal import SurrealClient

        client = SurrealClient(
            url=cold_settings.surreal_url,
            namespace=cold_settings.surreal_ns,
            database=cold_settings.surreal_db,
            user=cold_settings.surreal_user,
            password=cold_settings.surreal_pass,
        )
        try:
            rows = await client.query("SELECT name FROM schema_migration;")
        finally:
            await client.close()
        return len(rows or [])

    applied_count = asyncio.run(_count_applied())
    migration_files = list(Path(MIGRATIONS_DIR).glob("*.surql"))
    assert applied_count == len(migration_files), (
        f"expected {len(migration_files)} applied migrations, got {applied_count}"
    )
