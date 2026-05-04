from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentic_survey.api.admin import router as admin_router
from agentic_survey.auth import require_admin_session
from agentic_survey.domain.observation import MethodObservation
from agentic_survey.repository import InMemoryRepository, get_repository


def _build_app(*, authenticated: bool = True) -> tuple[FastAPI, InMemoryRepository]:
    repo = InMemoryRepository()
    app = FastAPI()
    app.dependency_overrides[get_repository] = lambda: repo
    if authenticated:
        app.dependency_overrides[require_admin_session] = lambda: SimpleNamespace(
            username="",
        )
    app.include_router(admin_router, prefix="/api")
    return app, repo


def _create_session(repo: InMemoryRepository) -> tuple[str, str]:
    campaign = repo.create_campaign(title="Demo", min_n=5, max_n=10)
    session = repo.start_interview_session(
        campaign_id=campaign.id,
        invite_id=None,
        consent_mode="anonymous",
        identity_label="",
        persona_snapshot={},
        pinned_endpoint="mini",
    )
    return campaign.id, session.id


def _append(
    repo: InMemoryRepository,
    *,
    id: str,
    campaign_id: str,
    session_id: str,
    body: str,
    created_at: datetime,
) -> None:
    asyncio.run(
        repo.append_method_observation(
            MethodObservation(
                id=id,
                session_id=session_id,
                campaign_id=campaign_id,
                author="operator",
                body=body,
                tags=[],
                created_at=created_at,
            )
        )
    )


def test_create_observation_requires_admin_session() -> None:
    app, repo = _build_app(authenticated=False)
    campaign_id, session_id = _create_session(repo)
    client = TestClient(app)

    response = client.post(
        f"/api/admin/campaigns/{campaign_id}/sessions/{session_id}/observations",
        json={"body": "probe felt thin"},
    )

    assert response.status_code == 401


def test_create_observation_returns_404_for_unknown_campaign() -> None:
    app, repo = _build_app()
    _campaign_id, session_id = _create_session(repo)
    client = TestClient(app)

    response = client.post(
        f"/api/admin/campaigns/missing/sessions/{session_id}/observations",
        json={"body": "probe felt thin"},
    )

    assert response.status_code == 404


def test_create_observation_returns_404_for_unknown_session() -> None:
    app, repo = _build_app()
    campaign_id, _session_id = _create_session(repo)
    client = TestClient(app)

    response = client.post(
        f"/api/admin/campaigns/{campaign_id}/sessions/missing/observations",
        json={"body": "probe felt thin"},
    )

    assert response.status_code == 404


def test_create_observation_rejects_empty_body() -> None:
    app, repo = _build_app()
    campaign_id, session_id = _create_session(repo)
    client = TestClient(app)

    response = client.post(
        f"/api/admin/campaigns/{campaign_id}/sessions/{session_id}/observations",
        json={"body": "   ", "tags": []},
    )

    assert response.status_code == 400
    assert "non-empty" in response.json()["detail"]


def test_create_observation_returns_created_payload() -> None:
    app, repo = _build_app()
    campaign_id, session_id = _create_session(repo)
    client = TestClient(app)

    response = client.post(
        f"/api/admin/campaigns/{campaign_id}/sessions/{session_id}/observations",
        json={"body": "  probe felt thin  ", "tags": [" Probe ", "probe", "R6"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == session_id
    assert body["campaign_id"] == campaign_id
    assert body["author"] == "operator"
    assert body["body"] == "probe felt thin"
    assert body["tags"] == ["probe", "r6"]
    assert body["created_at"]


def test_list_observations_returns_chronological_order() -> None:
    app, repo = _build_app()
    campaign_id, session_id = _create_session(repo)
    same_timestamp = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    _append(
        repo,
        id="mobs-b",
        campaign_id=campaign_id,
        session_id=session_id,
        body="second id",
        created_at=same_timestamp,
    )
    _append(
        repo,
        id="mobs-a",
        campaign_id=campaign_id,
        session_id=session_id,
        body="first id",
        created_at=same_timestamp,
    )
    client = TestClient(app)

    response = client.get(
        f"/api/admin/campaigns/{campaign_id}/sessions/{session_id}/observations",
    )

    assert response.status_code == 200
    observations = response.json()["observations"]
    assert [row["id"] for row in observations] == ["mobs-a", "mobs-b"]


def test_campaign_observations_jsonl_exports_campaign_rows() -> None:
    app, repo = _build_app()
    campaign_id, session_id = _create_session(repo)
    other_campaign_id, other_session_id = _create_session(repo)
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    _append(
        repo,
        id="mobs-1",
        campaign_id=campaign_id,
        session_id=session_id,
        body="probe quality changed",
        created_at=now,
    )
    _append(
        repo,
        id="mobs-2",
        campaign_id=other_campaign_id,
        session_id=other_session_id,
        body="not exported",
        created_at=now,
    )
    client = TestClient(app)

    response = client.get(f"/api/admin/campaigns/{campaign_id}/observations.jsonl")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    lines = [line for line in response.text.splitlines() if line]
    assert len(lines) == 1
    assert '"id": "mobs-1"' in lines[0]
    assert '"body": "probe quality changed"' in lines[0]
