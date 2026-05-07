"""Routing-matrix tests for litellm_config.yaml.

These exercise the loader directly so the five required runtime configurations
all resolve without fake aliases:

  1. mini + dynamo (separate endpoints)
  2. mini + OpenRouter
  3. only mini
  4. only dynamo
  5. only OpenRouter

Each test patches the SURVEY_* env vars to express one configuration, calls
``load_filtered_model_list``, and asserts the surviving rows. The loader must
keep at most one row per ``model_name``, ordered by per-role priority so the
operator's intent is unambiguous.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

import pytest

from agentic_survey.llm.router import load_filtered_model_list


CONFIG_PATH = (
    Path(__file__).resolve().parents[2]
    / "agentic_survey"
    / "llm"
    / "litellm_config.yaml"
)

CANONICAL_ALIASES: frozenset[str] = frozenset(
    {
        "mira-chatter",
        "mira-scientist",
        "validator",
        "analyst",
        "ingest",
        "embeddings",
    }
)


def _phase_env(**overrides: str) -> dict[str, str]:
    """Build an env mapping from a sane base, blanking the unset entries."""
    base = {
        "SURVEY_MINI_ENDPOINT_URL": "",
        "SURVEY_MINI_MODEL": "Nemotron-3-Nano-Omni-30B-A3B-Reasoning-UD-Q4_K_M",
        "SURVEY_DYNAMO_ENDPOINT_URL": "",
        "SURVEY_DYNAMO_MODEL": "nvidia-nemotron-3-nano-omni-30b-a3b-reasoning",
        "SURVEY_EMBEDDING_MODEL": "text-embedding-nomic-embed-text-v2-moe",
        "SURVEY_EMBEDDING_ENDPOINT_URL": "",
        "SURVEY_EMBEDDING_API_KEY": "lm-studio",
        "SURVEY_OPENROUTER_API_KEY": "",
        "SURVEY_OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
        "SURVEY_OPENROUTER_DYNAMO_MODEL": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "SURVEY_OPENROUTER_FALLBACK_ENABLED": "false",
    }
    base.update(overrides)
    return base


def _apply_env(monkeypatch: pytest.MonkeyPatch, env: Mapping[str, str]) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def _api_base_by_alias(rows: list[dict]) -> dict[str, str]:
    return {
        row["model_name"]: row["litellm_params"].get("api_base", "")
        for row in rows
    }


def _model_id_by_alias(rows: list[dict]) -> dict[str, str]:
    return {
        row["model_name"]: row["litellm_params"].get("model", "")
        for row in rows
    }


def _aliases(rows: list[dict]) -> set[str]:
    return {row["model_name"] for row in rows}


def test_no_fake_aliases_appear_anywhere(monkeypatch: pytest.MonkeyPatch) -> None:
    """Across every supported config the only model_names are the canonical six.

    The runtime resolves Brain A/B via ``mira-chatter`` / ``mira-scientist`` and
    the rest via ``validator`` / ``analyst`` / ``ingest`` / ``embeddings``.
    Inventing per-config aliases like ``mira-scientist-local`` or
    ``mira-chatter-or`` is forbidden — the loader picks among rows of the same
    name based on env presence, no source edits required.
    """
    configs = [
        _phase_env(
            SURVEY_MINI_ENDPOINT_URL="http://mini:8080/v1",
            SURVEY_DYNAMO_ENDPOINT_URL="http://dynamo:1234/v1",
        ),
        _phase_env(
            SURVEY_MINI_ENDPOINT_URL="http://mini:8080/v1",
            SURVEY_OPENROUTER_API_KEY="sk-or-v1-test",
            SURVEY_OPENROUTER_FALLBACK_ENABLED="true",
        ),
        _phase_env(SURVEY_MINI_ENDPOINT_URL="http://mini:8080/v1"),
        _phase_env(SURVEY_DYNAMO_ENDPOINT_URL="http://dynamo:1234/v1"),
        _phase_env(
            SURVEY_OPENROUTER_API_KEY="sk-or-v1-test",
            SURVEY_OPENROUTER_FALLBACK_ENABLED="true",
        ),
    ]
    for env in configs:
        _apply_env(monkeypatch, env)
        rows = load_filtered_model_list(CONFIG_PATH)
        observed = _aliases(rows)
        assert observed.issubset(CANONICAL_ALIASES), (
            f"unexpected aliases under env={env}: {observed - CANONICAL_ALIASES}"
        )


def test_phase_one_mini_plus_dynamo_pins_each_role_to_its_canonical_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both local endpoints up, no OR. Brain A on mini, Brain B and friends on dynamo."""
    env = _phase_env(
        SURVEY_MINI_ENDPOINT_URL="http://mini:8080/v1",
        SURVEY_DYNAMO_ENDPOINT_URL="http://dynamo:1234/v1",
    )
    _apply_env(monkeypatch, env)

    rows = load_filtered_model_list(CONFIG_PATH)
    api_base = _api_base_by_alias(rows)
    model_id = _model_id_by_alias(rows)

    assert api_base["mira-chatter"] == "http://mini:8080/v1"
    assert api_base["mira-scientist"] == "http://dynamo:1234/v1"
    assert api_base["validator"] == "http://dynamo:1234/v1"
    assert api_base["analyst"] == "http://dynamo:1234/v1"
    assert api_base["ingest"] == "http://dynamo:1234/v1"
    # Embedding endpoint defaults to the dynamo URL when no explicit override.
    assert api_base["embeddings"] in {"http://dynamo:1234/v1", ""}

    assert model_id["mira-chatter"].startswith("openai/")
    assert model_id["mira-scientist"].startswith("openai/")

    # No row should be duplicated (one survivor per role).
    aliases = [row["model_name"] for row in rows]
    assert len(aliases) == len(set(aliases))


def test_phase_two_mini_plus_openrouter_routes_scientist_through_or(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mini local up; dynamo down; OR enabled. Brain A on mini, Brain B and friends on OR."""
    env = _phase_env(
        SURVEY_MINI_ENDPOINT_URL="http://mini:8080/v1",
        SURVEY_OPENROUTER_API_KEY="sk-or-v1-test",
        SURVEY_OPENROUTER_FALLBACK_ENABLED="true",
    )
    _apply_env(monkeypatch, env)

    rows = load_filtered_model_list(CONFIG_PATH)
    api_base = _api_base_by_alias(rows)
    model_id = _model_id_by_alias(rows)

    assert api_base["mira-chatter"] == "http://mini:8080/v1"
    assert api_base["mira-scientist"] == "https://openrouter.ai/api/v1"
    assert api_base["validator"] == "https://openrouter.ai/api/v1"
    assert api_base["analyst"] == "https://openrouter.ai/api/v1"
    assert api_base["ingest"] == "https://openrouter.ai/api/v1"

    assert model_id["mira-scientist"].startswith("openrouter/")
    assert model_id["validator"].startswith("openrouter/")


def test_phase_three_only_mini_collapses_every_role_onto_mini(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _phase_env(SURVEY_MINI_ENDPOINT_URL="http://mini:8080/v1")
    _apply_env(monkeypatch, env)

    rows = load_filtered_model_list(CONFIG_PATH)
    api_base = _api_base_by_alias(rows)

    for alias in ("mira-chatter", "mira-scientist", "validator", "analyst", "ingest"):
        assert api_base[alias] == "http://mini:8080/v1", (
            f"alias {alias!r} did not collapse onto mini in phase 3: {api_base}"
        )


def test_phase_four_only_dynamo_collapses_every_role_onto_dynamo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _phase_env(SURVEY_DYNAMO_ENDPOINT_URL="http://dynamo:1234/v1")
    _apply_env(monkeypatch, env)

    rows = load_filtered_model_list(CONFIG_PATH)
    api_base = _api_base_by_alias(rows)

    for alias in ("mira-chatter", "mira-scientist", "validator", "analyst", "ingest"):
        assert api_base[alias] == "http://dynamo:1234/v1", (
            f"alias {alias!r} did not collapse onto dynamo in phase 4: {api_base}"
        )


def test_phase_five_only_openrouter_routes_every_chat_role_through_or(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _phase_env(
        SURVEY_OPENROUTER_API_KEY="sk-or-v1-test",
        SURVEY_OPENROUTER_FALLBACK_ENABLED="true",
    )
    _apply_env(monkeypatch, env)

    rows = load_filtered_model_list(CONFIG_PATH)
    api_base = _api_base_by_alias(rows)
    model_id = _model_id_by_alias(rows)

    for alias in ("mira-chatter", "mira-scientist", "validator", "analyst", "ingest"):
        assert api_base[alias] == "https://openrouter.ai/api/v1", (
            f"alias {alias!r} did not collapse onto OpenRouter in phase 5: {api_base}"
        )
        assert model_id[alias].startswith("openrouter/")


def test_each_role_has_exactly_one_surviving_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The loader must dedupe per ``model_name`` so simple-shuffle picks deterministically.

    Without per-role dedup, a phase-1 config with both local and OR rows for
    ``validator`` would have LiteLLM rotate randomly between local and hosted
    backends. The fix makes the loader keep the first (highest-priority) row
    whose env requirements are satisfied.
    """
    env = _phase_env(
        SURVEY_MINI_ENDPOINT_URL="http://mini:8080/v1",
        SURVEY_DYNAMO_ENDPOINT_URL="http://dynamo:1234/v1",
        SURVEY_OPENROUTER_API_KEY="sk-or-v1-test",
        SURVEY_OPENROUTER_FALLBACK_ENABLED="true",
    )
    _apply_env(monkeypatch, env)

    rows = load_filtered_model_list(CONFIG_PATH)
    aliases = [row["model_name"] for row in rows]
    duplicates = {alias for alias in aliases if aliases.count(alias) > 1}
    assert not duplicates, f"loader produced duplicate aliases: {duplicates}"


def test_loader_strips_metadata_keys_from_returned_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Internal gate keys (``_requires_env``, ``_openrouter_fallback``) must not
    leak into the LiteLLM model_list — Router rejects unknown row keys."""
    env = _phase_env(
        SURVEY_MINI_ENDPOINT_URL="http://mini:8080/v1",
        SURVEY_DYNAMO_ENDPOINT_URL="http://dynamo:1234/v1",
        SURVEY_OPENROUTER_API_KEY="sk-or-v1-test",
        SURVEY_OPENROUTER_FALLBACK_ENABLED="true",
    )
    _apply_env(monkeypatch, env)

    rows = load_filtered_model_list(CONFIG_PATH)
    for row in rows:
        assert "_requires_env" not in row
        assert "_openrouter_fallback" not in row
