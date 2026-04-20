from __future__ import annotations

import asyncio
import json

from agentic_survey.config import get_settings
from agentic_survey.db.surreal import SurrealClient
from agentic_survey.llm.catalog import seed_entries


async def _table_has_rows(client: SurrealClient) -> bool:
    raw = await client.query_raw("SELECT * FROM model_catalog LIMIT 1;")
    results = raw.get("result", [])
    if not results:
        return False
    first = results[0]
    if first.get("status") != "OK":
        raise RuntimeError(f"Catalog query failed: {first}")
    return bool(first.get("result"))


async def _seed(client: SurrealClient) -> int:
    if await _table_has_rows(client):
        print("Model catalog already seeded; skipping.")
        return 0

    statements = []
    for entry in seed_entries():
        payload = entry.model_dump(
            exclude={"created_at", "updated_at"},
            exclude_none=True,
        )
        statements.append(f"CREATE model_catalog CONTENT {json.dumps(payload)};")

    raw = await client.query_raw("\n".join(statements))
    for result in raw.get("result", []):
        if result.get("status") != "OK":
            raise RuntimeError(f"Catalog seed failed: {result}")
    print(f"Seeded {len(statements)} model_catalog rows.")
    return 0


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
        return await _seed(client)
    finally:
        await client.close()


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
