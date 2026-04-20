"""Apply the canonical SurrealDB schema.

Pre-1.0: there are no migrations. Every ``DEFINE`` in ``schema.surql``
is guarded by ``IF NOT EXISTS`` so re-application is idempotent. When
the schema needs a breaking change, drop the database and re-apply:

    docker compose -f infra/docker-compose.local.yml down -v
    docker compose -f infra/docker-compose.local.yml up -d surrealdb
    cd services/api && uv run python -m agentic_survey.db.schema
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from agentic_survey.config import get_settings
from agentic_survey.db.surreal import SurrealClient

logger = logging.getLogger(__name__)

SCHEMA_FILE = Path(__file__).resolve().parent / "schema.surql"


async def apply_schema(client: SurrealClient) -> None:
    """Apply ``schema.surql`` in a single RPC round-trip.

    Raises ``RuntimeError`` if any statement fails so callers (runtime
    boot, tests, ops scripts) get a loud failure instead of a silent
    partial apply.
    """
    raw = await client.query_raw(SCHEMA_FILE.read_text())
    results = raw.get("result") or []
    for entry in results:
        if isinstance(entry, dict) and entry.get("status") and entry.get("status") != "OK":
            raise RuntimeError(f"schema apply failed: {entry}")


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
        await apply_schema(client)
        print(f"Schema applied to {settings.surreal_ns}/{settings.surreal_db}.")
    finally:
        await client.close()
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
