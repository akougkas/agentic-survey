from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import yaml

from agentic_survey.agents.brain_a import stream_brain_a
from agentic_survey.agents.brain_b_loop import run_brain_b_with_tools
from agentic_survey.agents.tools.registry import ToolRegistry
from agentic_survey.domain.intent import BrainBIntent
from agentic_survey.domain.tools import GetUserInputOptions


CONFIG_PATH = (
    Path(__file__).resolve().parents[2]
    / "agentic_survey"
    / "llm"
    / "litellm_config.yaml"
)


def _intent_json() -> str:
    intent = BrainBIntent(
        active_axis="R1",
        question_intent="Ask for a concrete recent moment.",
        get_user_input=GetUserInputOptions(
            question="What happened most recently?",
            options=["A recent moment", "The blocker", "Discuss this more."],
            allow_free_text=True,
        ),
        retrieval_used=False,
        retrieval_chunks=[],
    )
    return intent.model_dump_json()


def _load_litellm_config() -> dict[str, Any]:
    return yaml.safe_load(CONFIG_PATH.read_text()) or {}


def _entry_by_name(config: dict[str, Any], name: str) -> dict[str, Any]:
    for entry in config["model_list"]:
        if entry["model_name"] == name:
            return entry
    raise AssertionError(f"missing LiteLLM model entry {name!r}")


def _forbidden_schema_annotations(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"default", "title"}:
                found.append(key)
            found.extend(_forbidden_schema_annotations(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_forbidden_schema_annotations(item))
    return found


def test_litellm_aliases_are_pinned_to_runtime_envs() -> None:
    config = _load_litellm_config()

    chatter = _entry_by_name(config, "mira-chatter")
    assert chatter["litellm_params"] == {
        "model": "openai/${SURVEY_MINI_MODEL}",
        "api_base": "${SURVEY_MINI_ENDPOINT_URL}",
    }

    for alias in ["mira-scientist", "validator", "analyst", "ingest"]:
        entry = _entry_by_name(config, alias)
        assert entry["litellm_params"] == {
            "model": "openai/${SURVEY_DYNAMO_MODEL}",
            "api_base": "${SURVEY_DYNAMO_ENDPOINT_URL}",
        }

    embeddings = _entry_by_name(config, "embeddings")
    assert embeddings["litellm_params"] == {
        "model": "openai/${SURVEY_EMBEDDING_MODEL}",
        "api_base": "${SURVEY_DYNAMO_ENDPOINT_URL}",
    }


def test_litellm_aliases_do_not_cross_fallback_between_brains() -> None:
    config = _load_litellm_config()
    router_settings = config.get("router_settings", {})

    assert router_settings.get("fallbacks") in (None, [])


class _BrainAStreamRouter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def acompletion(self, **kwargs: Any):
        self.calls.append(kwargs)

        async def _stream():
            yield {"choices": [{"delta": {"content": "hello"}}]}

        return _stream()


def test_brain_a_requests_mira_chatter_alias() -> None:
    async def _run() -> _BrainAStreamRouter:
        router = _BrainAStreamRouter()
        chunks = [
            chunk
            async for chunk in stream_brain_a(
                role="mira-chatter",
                prompt_md_path="interviewer_brain_a.md",
                transcript_tail=[],
                brain_b_intent=BrainBIntent.model_validate_json(_intent_json()),
                persona="",
                router=router,
            )
        ]
        assert chunks == ["hello"]
        return router

    router = asyncio.run(_run())

    assert router.calls[0]["model"] == "mira-chatter"
    assert router.calls[0]["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


class _BrainBRouter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def acompletion(self, **kwargs: Any):
        self.calls.append(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": _intent_json(),
                    }
                }
            ]
        }


def test_brain_b_requests_mira_scientist_alias_and_parses_reasoning_json() -> None:
    async def _run() -> tuple[_BrainBRouter, BrainBIntent]:
        router = _BrainBRouter()
        result = await run_brain_b_with_tools(
            surface="interviewer",
            system_context=[],
            transcript_tail=[],
            registry=ToolRegistry([]),
            router=router,
            rubric_axes=[],
        )
        return router, result.intent

    router, intent = asyncio.run(_run())

    assert router.calls[0]["model"] == "mira-scientist"
    assert router.calls[0]["response_format"]["json_schema"]["name"] == "brain_b_intent"
    schema = router.calls[0]["response_format"]["json_schema"]["schema"]
    assert _forbidden_schema_annotations(schema) == []
    assert router.calls[0]["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True
    assert intent.active_axis == "R1"
