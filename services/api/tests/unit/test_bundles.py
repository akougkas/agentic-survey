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


def test_chat_thinking_messages_default_present_and_nonempty() -> None:
    manifest = ProductBundleManifest.model_validate(
        {
            "slug": "demo",
            "name": "Demo",
        }
    )

    bank = manifest.ui.chat.thinking_messages
    assert len(bank) >= 8
    assert all(isinstance(line, str) and line.strip() for line in bank)
    assert bank[0] == "Thinking..."


def test_chat_thinking_messages_bundle_override_round_trips() -> None:
    manifest = ProductBundleManifest.model_validate(
        {
            "slug": "demo",
            "name": "Demo",
            "ui": {
                "chat": {
                    "thinking_messages": [
                        "Reading between your lines.",
                        "Synthesizing the next question.",
                    ],
                },
            },
        }
    )

    assert manifest.ui.chat.thinking_messages == [
        "Reading between your lines.",
        "Synthesizing the next question.",
    ]
