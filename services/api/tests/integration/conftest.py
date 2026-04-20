"""Shared fixtures for the SurrealDB integration suite (M7.5).

The unit suite exercises ``InMemoryRepository``; this tier boots the
local ``surrealdb`` container from ``infra/docker-compose.local.yml``
and runs the hot queries against a live database. Tests that request
``surreal_repository`` are skipped cleanly on a docker-less box so
``make verify`` still passes without Docker.
"""

from __future__ import annotations

import asyncio
import socket
import subprocess
import time
from collections.abc import Generator
from pathlib import Path

import pytest

from agentic_survey.config import Settings
from agentic_survey.db.schema import apply_schema
from agentic_survey.db.surreal import SurrealClient
from agentic_survey.db.surreal_repository import SurrealRepository

REPO_ROOT = Path(__file__).resolve().parents[4]
COMPOSE_FILE = REPO_ROOT / "infra" / "docker-compose.local.yml"
SURREAL_HOST = "127.0.0.1"
SURREAL_PORT = 8400
SURREAL_URL = f"ws://{SURREAL_HOST}:{SURREAL_PORT}"
TEST_NS = "agentic_survey_it"
TEST_DB = "integration"


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
        return False
    return result.returncode == 0


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


async def _probe_authenticated() -> bool:
    """Attempt a root-level signin + trivial query.

    Port-open fires as soon as the TCP listener binds, but the storage
    backend may still be initializing on a cold container. An authenticated
    round-trip is the real readiness signal.
    """
    from surrealdb import AsyncSurreal

    db = AsyncSurreal(SURREAL_URL)
    try:
        await db.signin({"username": "root", "password": "root"})
        await db.query("RETURN true;")
        return True
    except Exception:
        return False
    finally:
        close = getattr(db, "close", None)
        if callable(close):
            result = close()
            if result is not None:
                try:
                    await result
                except Exception:
                    pass


def _wait_for_ready(deadline: float) -> bool:
    while time.monotonic() < deadline:
        if _port_open(SURREAL_HOST, SURREAL_PORT) and asyncio.run(
            _probe_authenticated()
        ):
            return True
        time.sleep(0.5)
    return False


def _ensure_surreal_running() -> None:
    deadline = time.monotonic() + 2.0
    if _wait_for_ready(deadline):
        return
    if not COMPOSE_FILE.exists():
        pytest.skip(f"docker-compose.local.yml not found at {COMPOSE_FILE}")
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "surrealdb"],
        check=False,
        capture_output=True,
        timeout=60,
    )
    if result.returncode != 0:
        pytest.skip(
            "docker compose up failed: "
            + result.stderr.decode(errors="replace").strip()
        )
    if not _wait_for_ready(time.monotonic() + 30.0):
        pytest.skip(f"SurrealDB did not accept root signin within 30s")


def _build_settings(*, ns: str = TEST_NS, db: str = TEST_DB) -> Settings:
    return Settings(
        surreal_url=SURREAL_URL,
        surreal_ns=ns,
        surreal_db=db,
        surreal_user="root",
        surreal_pass="root",
        repository="surreal",
    )


async def _root_query(settings: Settings, statement: str) -> None:
    """Run a root-scope statement (no USE).

    ``SurrealClient`` always ``use()``s a namespace before querying, but
    ``REMOVE NAMESPACE`` on the same NS we are USE'd on is awkward: use
    the raw ``AsyncSurreal`` driver directly so root statements run
    cleanly.
    """
    from surrealdb import AsyncSurreal

    db = AsyncSurreal(settings.surreal_url)
    try:
        await db.signin(
            {"username": settings.surreal_user, "password": settings.surreal_pass}
        )
        await db.query(statement)
    finally:
        close = getattr(db, "close", None)
        if callable(close):
            result = close()
            if result is not None:
                await result


async def _apply(settings: Settings) -> None:
    client = SurrealClient(
        url=settings.surreal_url,
        namespace=settings.surreal_ns,
        database=settings.surreal_db,
        user=settings.surreal_user,
        password=settings.surreal_pass,
    )
    try:
        await apply_schema(client)
    finally:
        await client.close()


def drop_namespace(settings: Settings) -> None:
    """Drop the configured namespace at root scope (public helper)."""
    asyncio.run(
        _root_query(settings, f"REMOVE NAMESPACE IF EXISTS {settings.surreal_ns};")
    )


def apply_schema_sync(settings: Settings) -> None:
    """Apply the canonical schema to the configured namespace."""
    asyncio.run(_apply(settings))


@pytest.fixture(scope="session")
def surreal_settings() -> Settings:
    if not _docker_available():
        pytest.skip("docker unavailable")
    _ensure_surreal_running()
    return _build_settings()


@pytest.fixture(scope="session")
def surreal_repository(
    surreal_settings: Settings,
) -> Generator[SurrealRepository, None, None]:
    drop_namespace(surreal_settings)
    apply_schema_sync(surreal_settings)
    repo = SurrealRepository(surreal_settings)
    try:
        yield repo
    finally:
        drop_namespace(surreal_settings)
