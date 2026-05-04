from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentic_survey.admin_surfaces import ADMIN_SURFACES
from agentic_survey.bundles import ProductBundleManifest


def test_admin_surfaces_omitted_passes_as_none() -> None:
    manifest = ProductBundleManifest.model_validate(
        {
            "slug": "demo",
            "name": "Demo",
        }
    )

    assert manifest.ui.admin.surfaces is None


def test_admin_surfaces_valid_allowlist_preserves_order_and_deduplicates() -> None:
    manifest = ProductBundleManifest.model_validate(
        {
            "slug": "demo",
            "name": "Demo",
            "ui": {
                "admin": {
                    "surfaces": ["campaigns", "catalog", "campaigns", "answers"],
                },
            },
        }
    )

    assert manifest.ui.admin.surfaces == ["campaigns", "catalog", "answers"]


def test_admin_surfaces_unknown_key_names_offender_and_known_set() -> None:
    with pytest.raises(ValidationError) as caught:
        ProductBundleManifest.model_validate(
            {
                "slug": "demo",
                "name": "Demo",
                "ui": {
                    "admin": {
                        "surfaces": ["campaigns", "bogus"],
                    },
                },
            }
        )

    message = str(caught.value)
    assert "bogus" in message
    for surface in ADMIN_SURFACES:
        assert surface in message
