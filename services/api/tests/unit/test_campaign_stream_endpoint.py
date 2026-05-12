"""Tests for GET /api/campaigns/{id}/stream and the graph snapshot endpoint.

The stream endpoint is admin-gated, returns SSE frames carrying a monotonic
``id`` (``seq``), and replays the ring buffer for reconnecting clients.

The stream generator is tested directly against a fake Request rather than
through ``TestClient`` so each test finishes in milliseconds. The endpoint
wiring (auth gate, 404 handling, query param parsing) is covered via
``TestClient`` with the generator stubbed to drain immediately.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentic_survey.api.admin import router as admin_router
from agentic_survey.api.campaigns import (
    _campaign_event_stream,
    _sse_frame,
    router as campaigns_router,
)
from agentic_survey.auth import require_admin_session
from agentic_survey.engine.event_bus import (
    EventEnvelope,
    get_event_bus,
    reset_event_bus,
)
from agentic_survey.engine.interview_loop import InterviewEvent
from agentic_survey.repository import InMemoryRepository, get_repository


class _FakeRequest:
    """Minimal stand-in for fastapi.Request used by the stream generator."""

    def __init__(self, disconnect_after_yields: int) -> None:
        self._remaining = disconnect_after_yields

    async def is_disconnected(self) -> bool:
        if self._remaining <= 0:
            return True
        self._remaining -= 1
        return False


def _build_app() -> tuple[FastAPI, InMemoryRepository]:
    reset_event_bus()
    repo = InMemoryRepository()
    app = FastAPI()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[require_admin_session] = lambda: object()
    app.include_router(campaigns_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")
    return app, repo


async def _drain(gen: Any) -> list[bytes]:
    """Consume the async-gen fully. The fake request flips ``is_disconnected``
    so the generator exits cleanly once it has yielded the ring replay."""
    out: list[bytes] = []
    async for chunk in gen:
        out.append(chunk)
    return out


# ---------- Frame formatter ----------


def test_sse_frame_format() -> None:
    env = EventEnvelope(seq=7, name="graph_delta", data={"add_nodes": [{"id": "c1"}]})
    out = _sse_frame(env).decode("utf-8")
    lines = out.split("\n")
    assert lines[0] == "id: 7"
    assert lines[1] == "event: graph_delta"
    assert lines[2].startswith("data: ")
    assert json.loads(lines[2].removeprefix("data: ")) == {"add_nodes": [{"id": "c1"}]}
    assert out.endswith("\n\n")


# ---------- Stream generator (direct, no HTTP) ----------


def test_generator_replays_ring() -> None:
    reset_event_bus()
    repo = InMemoryRepository()
    get_event_bus().publish_many(
        "cid",
        [
            InterviewEvent(name="turn_start", data={"session_id": "s1"}),
            InterviewEvent(name="graph_delta", data={"add_nodes": []}),
        ],
    )
    # is_disconnected() returns False twice (one check per replay yield) then True.
    request = _FakeRequest(disconnect_after_yields=2)

    chunks = asyncio.run(_drain(_campaign_event_stream("cid", request, since=-1, repository=repo)))
    assert len(chunks) == 2
    assert b"id: 0\nevent: turn_start\n" in chunks[0]
    assert b"id: 1\nevent: graph_delta\n" in chunks[1]


def test_generator_since_filters_out_old_events() -> None:
    reset_event_bus()
    repo = InMemoryRepository()
    get_event_bus().publish_many(
        "cid",
        [InterviewEvent(name=n, data={}) for n in ("a", "b", "c")],
    )
    request = _FakeRequest(disconnect_after_yields=2)

    chunks = asyncio.run(_drain(_campaign_event_stream("cid", request, since=0, repository=repo)))
    assert len(chunks) == 2
    assert b"id: 1\n" in chunks[0]
    assert b"id: 2\n" in chunks[1]


def test_generator_unsubscribes_on_disconnect() -> None:
    """The ``finally`` in the generator must drop the subscriber queue."""
    reset_event_bus()
    repo = InMemoryRepository()
    get_event_bus().publish_many("cid", [InterviewEvent(name="x", data={})])
    bus = get_event_bus()
    request = _FakeRequest(disconnect_after_yields=1)

    asyncio.run(_drain(_campaign_event_stream("cid", request, since=-1, repository=repo)))

    assert bus.subscriber_count("cid") == 0


def test_generator_respects_disconnect_before_replay() -> None:
    """If the client hangs up before any replay yield, nothing is emitted."""
    reset_event_bus()
    repo = InMemoryRepository()
    get_event_bus().publish_many("cid", [InterviewEvent(name="x", data={})])
    request = _FakeRequest(disconnect_after_yields=0)

    chunks = asyncio.run(_drain(_campaign_event_stream("cid", request, since=-1, repository=repo)))
    assert chunks == []


# ---------- Endpoint wiring (HTTP-level) ----------


def test_stream_endpoint_404_for_unknown_campaign() -> None:
    app, _ = _build_app()
    client = TestClient(app)
    response = client.get("/api/campaigns/missing/stream")
    assert response.status_code == 404


def test_stream_endpoint_requires_admin_session() -> None:
    reset_event_bus()
    repo = InMemoryRepository()
    app = FastAPI()
    app.dependency_overrides[get_repository] = lambda: repo
    app.include_router(campaigns_router, prefix="/api")
    campaign = repo.create_campaign(title="Demo", min_n=5, max_n=10)

    client = TestClient(app)
    response = client.get(f"/api/campaigns/{campaign.id}/stream")
    assert response.status_code == 401


# ---------- Graph snapshot endpoint ----------


def test_graph_snapshot_empty_campaign() -> None:
    app, repo = _build_app()
    campaign = repo.create_campaign(title="Demo", min_n=5, max_n=10)

    client = TestClient(app)
    response = client.get(f"/api/admin/campaigns/{campaign.id}/graph")
    assert response.status_code == 200
    body = response.json()
    assert body["campaign_id"] == campaign.id
    assert body["nodes"] == []
    assert body["edges"] == []
    assert body["latest_event_seq"] == -1


def test_graph_snapshot_404_for_unknown_campaign() -> None:
    app, _ = _build_app()
    client = TestClient(app)
    response = client.get("/api/admin/campaigns/missing/graph")
    assert response.status_code == 404


def test_graph_snapshot_reports_latest_event_seq_after_publish() -> None:
    app, repo = _build_app()
    campaign = repo.create_campaign(title="Demo", min_n=5, max_n=10)
    get_event_bus().publish_many(
        campaign.id,
        [InterviewEvent(name="graph_delta", data={}), InterviewEvent(name="turn_complete", data={})],
    )

    client = TestClient(app)
    response = client.get(f"/api/admin/campaigns/{campaign.id}/graph")
    assert response.status_code == 200
    assert response.json()["latest_event_seq"] == 1
