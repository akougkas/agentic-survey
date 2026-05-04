from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentic_survey.api.system import router as system_router
from agentic_survey.bundles import REPO_ROOT
from agentic_survey.config import get_settings


def _context_for_bundle(monkeypatch, bundle_dir: Path) -> dict[str, object]:
    monkeypatch.setenv("SURVEY_PRODUCT_BUNDLE_DIR", str(bundle_dir))
    get_settings.cache_clear()
    app = FastAPI()
    app.include_router(system_router, prefix="/api")
    try:
        response = TestClient(app).get("/api/system/context")
    finally:
        get_settings.cache_clear()
    assert response.status_code == 200
    return response.json()


def test_system_context_demo_admin_surfaces_allowlist_is_none(monkeypatch) -> None:
    payload = _context_for_bundle(
        monkeypatch,
        REPO_ROOT / "examples" / "product-bundles" / "demo",
    )

    assert payload["bundle_slug"] == "demo"
    assert payload["admin_surfaces_allowlist"] is None


def test_system_context_citadl_admin_surfaces_allowlist_is_configured(monkeypatch) -> None:
    payload = _context_for_bundle(monkeypatch, REPO_ROOT / "citadl" / "bundle")

    assert payload["bundle_slug"] == "citadl"
    assert payload["admin_surfaces_allowlist"] == [
        "catalog",
        "campaigns",
        "sessions",
        "transcripts",
        "answers",
        "invites",
    ]
