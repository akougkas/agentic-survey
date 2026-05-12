"""Apply the canonical schema against a fresh SurrealDB namespace.

Purges the test NS, runs ``apply_schema`` once, and asserts every table
the file defines is materialised. Also verifies that re-applying is a
no-op (every ``DEFINE`` is guarded by ``IF NOT EXISTS``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator

import pytest

from agentic_survey.config import Settings
from agentic_survey.db.schema import SCHEMA_FILE

from .conftest import (
    SURREAL_URL,
    _docker_available,
    _ensure_surreal_running,
    apply_schema_sync,
    drop_namespace,
)

COLD_NS = "agentic_survey_it_cold"
COLD_DB = "cold"

# Every SCHEMAFULL / RELATION table defined in schema.surql.
# Update this list when schema.surql gains a new table.
EXPECTED_TABLES = {
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
    "llm_audit",
    "question_answer",
    "method_observation",
    "knowledge_source",
    "knowledge_chunk",
    "retrieval_audit",
    "concept",
    "mentioned_with",
    "contradicts",
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


def test_schema_manifest_matches_expected_tables() -> None:
    """Drift guard: every ``DEFINE TABLE`` in schema.surql is in EXPECTED_TABLES."""
    discovered: set[str] = set()
    for line in SCHEMA_FILE.read_text().splitlines():
        stripped = line.strip()
        prefix = "DEFINE TABLE IF NOT EXISTS "
        if not stripped.startswith(prefix):
            continue
        name = stripped[len(prefix):].split()[0]
        discovered.add(name)
    assert discovered, "schema.surql defines no tables"
    assert discovered == EXPECTED_TABLES, (
        f"schema drift: extra={discovered - EXPECTED_TABLES!r}, "
        f"missing={EXPECTED_TABLES - discovered!r}"
    )


def test_cold_start_creates_every_table(cold_settings: Settings) -> None:
    apply_schema_sync(cold_settings)
    info = asyncio.run(_info_for_db(cold_settings))
    tables = info.get("tables") or {}
    assert isinstance(tables, dict), f"INFO.tables not a dict: {type(tables).__name__}"
    missing = EXPECTED_TABLES - set(tables.keys())
    assert not missing, f"apply_schema did not create tables: {sorted(missing)}"


def test_apply_schema_is_idempotent(cold_settings: Settings) -> None:
    """Re-apply is a no-op; every ``DEFINE`` has ``IF NOT EXISTS``."""
    apply_schema_sync(cold_settings)
    apply_schema_sync(cold_settings)
    info = asyncio.run(_info_for_db(cold_settings))
    tables = info.get("tables") or {}
    missing = EXPECTED_TABLES - set(tables.keys())
    assert not missing, f"tables disappeared after second apply: {sorted(missing)}"
