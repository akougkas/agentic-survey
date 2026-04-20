from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from agentic_survey.config import get_settings
from agentic_survey.db.surreal import SurrealClient

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent

SCHEMA_MIGRATION_BOOTSTRAP = """
DEFINE TABLE IF NOT EXISTS schema_migration SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS name ON TABLE schema_migration TYPE string;
DEFINE FIELD IF NOT EXISTS applied_at ON TABLE schema_migration TYPE datetime DEFAULT time::now();
DEFINE INDEX IF NOT EXISTS schema_migration_name ON TABLE schema_migration COLUMNS name UNIQUE;
""".strip()


def _discover_migrations() -> list[Path]:
    return sorted(path for path in MIGRATIONS_DIR.glob("*.surql") if path.is_file())


def _check_raw(label: str, raw: dict) -> None:
    results = raw.get("result") or []
    for entry in results:
        if isinstance(entry, dict) and entry.get("status") and entry.get("status") != "OK":
            raise RuntimeError(f"{label} failed: {entry}")


async def _fetch_applied(client: SurrealClient) -> set[str]:
    rows = await client.query("SELECT name FROM schema_migration;")
    applied: set[str] = set()
    for row in rows or []:
        name = row.get("name") if isinstance(row, dict) else None
        if isinstance(name, str):
            applied.add(name)
    return applied


async def apply_migrations(client: SurrealClient) -> list[str]:
    bootstrap_raw = await client.query_raw(SCHEMA_MIGRATION_BOOTSTRAP)
    _check_raw("schema_migration bootstrap", bootstrap_raw)
    applied = await _fetch_applied(client)
    migrations = _discover_migrations()
    newly_applied: list[str] = []
    for path in migrations:
        if path.name in applied:
            continue
        raw = await client.query_raw(path.read_text())
        _check_raw(path.name, raw)
        await client.query(
            "CREATE schema_migration CONTENT { name: $name };",
            {"name": path.name},
        )
        newly_applied.append(path.name)
    return newly_applied


async def _run() -> int:
    settings = get_settings()
    client = SurrealClient(
        url=settings.surreal_url,
        namespace=settings.surreal_ns,
        database=settings.surreal_db,
        user=settings.surreal_user,
        password=settings.surreal_pass,
    )
    try:
        newly_applied = await apply_migrations(client)
        if newly_applied:
            print("Migrations applied: " + ", ".join(newly_applied))
        else:
            print("Migrations already applied.")
    finally:
        await client.close()
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
