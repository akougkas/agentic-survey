"""Catalog-driven request shape for Brain A and Brain B.

Closes B4 (Brain A and Brain B were calling the LiteLLM router directly with a
hardcoded ``set_lmstudio_thinking(enabled=False)`` call, so the catalog's
``reasoning_mode`` was advisory only). After the fix both surfaces resolve the
catalog at request build time and call ``apply_reasoning_settings`` so the
chatter role stays reasoning-off and the scientist role stays reasoning-on
regardless of which endpoint the operator points at.
"""
from __future__ import annotations

import asyncio
from typing import Any

from agentic_survey.agents.brain_a import stream_brain_a
from agentic_survey.agents.brain_b_loop import run_brain_b_with_tools
from agentic_survey.agents.tools.registry import ToolRegistry
from agentic_survey.domain.intent import BrainBIntent
from agentic_survey.domain.tools import GetUserInputOptions
from agentic_survey.llm.catalog import CatalogResolution
from agentic_survey.llm.reasoning import (
    reasoning_completion_tokens,
    visible_reply_max_tokens,
)


def _intent_json() -> str:
    return BrainBIntent(
        active_axis="R1",
        question_intent="Ask for a concrete recent moment.",
        get_user_input=GetUserInputOptions(
            question="What did the morning queue look like?",
            options=["Tape backlog", "Globus pull", "Discuss this more."],
            allow_free_text=True,
        ),
    ).model_dump_json()


def _scientist_resolution(
    *, mode: str = "on", temperature: float | None = 0.3
) -> CatalogResolution:
    return CatalogResolution(
        role="scientist",
        source="catalog_default",
        catalog_id="scientist-default",
        endpoint="scientist",
        model_id="nvidia-nemotron-3-nano-omni-30b-a3b-reasoning",
        api_base="http://scientist-host:1234/v1",
        reasoning_mode=mode,  # type: ignore[arg-type]
        reasoning_kwarg="enable_thinking",
        temperature=temperature,
    )


def _chatter_resolution(
    *, mode: str = "off", temperature: float | None = 0.7
) -> CatalogResolution:
    return CatalogResolution(
        role="chatter",
        source="catalog_default",
        catalog_id="chatter-default",
        endpoint="chatter",
        model_id="AgenticQwen-30B-A3B-i1-Q4_K_M",
        api_base="http://chatter-host:8080/v1",
        reasoning_mode=mode,  # type: ignore[arg-type]
        reasoning_kwarg="enable_thinking",
        temperature=temperature,
    )


class _BrainAStreamRouter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def acompletion(self, **kwargs: Any):
        self.calls.append(kwargs)

        async def _stream():
            yield {"choices": [{"delta": {"content": "ok"}}]}

        return _stream()


class _BrainBRouter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def acompletion(self, **kwargs: Any) -> dict[str, Any]:
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


def test_brain_a_request_applies_chatter_reasoning_off() -> None:
    """The chatter role must land with enable_thinking=False, reasoning_effort=minimal,
    and a max_tokens floor wide enough to absorb LM Studio's reasoning leak.

    LM Studio ignores ``chat_template_kwargs.enable_thinking=false`` for
    reasoning models like Nemotron OMNI, so it streams ~200-500 reasoning tokens
    before any visible content. With the prior 512-token cap the entire budget
    landed in ``reasoning_content`` and ``delta.content`` stayed empty, which
    produced the empty agent turn that B11 reported.
    """
    router = _BrainAStreamRouter()
    intent = BrainBIntent.model_validate_json(_intent_json())

    async def _run() -> None:
        async for _chunk in stream_brain_a(
            role="mira-chatter",
            prompt_md_path="interviewer_brain_a.md",
            transcript_tail=[],
            brain_b_intent=intent,
            persona="",
            router=router,
            catalog_resolution=_chatter_resolution(),
        ):
            pass

    asyncio.run(_run())

    assert len(router.calls) == 1
    request = router.calls[0]
    extra_body = request.get("extra_body") or {}
    chat_template_kwargs = extra_body.get("chat_template_kwargs") or {}
    assert chat_template_kwargs.get("enable_thinking") is False
    assert request.get("reasoning_effort") == "minimal"
    # The visible cap floor must absorb reasoning leakage on LM Studio. 4096 is
    # the post-fix default; bumping above gemma's natural emission is harmless
    # because the model stops at EOS.
    assert request["max_tokens"] >= 4096
    assert request["max_tokens"] >= visible_reply_max_tokens()


def test_brain_b_planning_request_applies_scientist_reasoning_on() -> None:
    """Scientist catalog default is reasoning_mode='on'; Brain B must honor that.

    Hardcoding ``thinking_enabled=False`` made the catalog advisory and meant
    flipping endpoints did not change request shape. The fix routes Brain B's
    completion call through ``apply_reasoning_settings`` so enable_thinking
    matches the catalog and max_tokens reserves enough headroom for the full
    BrainBIntent JSON plus the model's reasoning preamble.
    """
    router = _BrainBRouter()

    async def _run() -> None:
        await run_brain_b_with_tools(
            surface="interviewer",
            system_context=[],
            transcript_tail=[],
            registry=ToolRegistry([]),
            router=router,
            rubric_axes=[],
            catalog_resolution=_scientist_resolution(mode="on"),
        )

    asyncio.run(_run())

    assert len(router.calls) >= 1
    request = router.calls[0]
    extra_body = request.get("extra_body") or {}
    chat_template_kwargs = extra_body.get("chat_template_kwargs") or {}
    assert chat_template_kwargs.get("enable_thinking") is True
    assert request.get("reasoning_effort") == "high"
    assert request["max_tokens"] >= reasoning_completion_tokens()
    assert "response_format" in request
    assert "tools" not in request
    assert "tool_choice" not in request


def test_brain_b_request_honors_per_call_reasoning_budget() -> None:
    """run_brain_b_with_tools accepts a per-call reasoning budget for warmup paths.

    The pre-plan warmup passes a tighter budget (``preplan_reasoning_budget_tokens``)
    so the first plan lands faster than a full reasoning round-trip. The
    catalog resolution carries the default budget; the per-call override has to
    win when supplied.
    """
    router = _BrainBRouter()
    custom_budget = 1024

    async def _run() -> None:
        await run_brain_b_with_tools(
            surface="interviewer",
            system_context=[],
            transcript_tail=[],
            registry=ToolRegistry([]),
            router=router,
            rubric_axes=[],
            catalog_resolution=_scientist_resolution(mode="on"),
            reasoning_budget_tokens=custom_budget,
        )

    asyncio.run(_run())

    request = router.calls[0]
    assert request["max_tokens"] == reasoning_completion_tokens(custom_budget)
    extra_body = request.get("extra_body") or {}
    chat_template_kwargs = extra_body.get("chat_template_kwargs") or {}
    assert chat_template_kwargs.get("enable_thinking") is True
    assert "response_format" in request


def test_brain_a_default_resolution_falls_back_to_mini_chatter_off() -> None:
    """When no resolution is passed Brain A still produces a chatter-shaped request.

    Production wiring will plumb the resolution from the LLMClient/catalog,
    but unit tests and any straggling caller that omits it should land on the
    same chatter-off shape so behavior degrades safely.
    """
    router = _BrainAStreamRouter()
    intent = BrainBIntent.model_validate_json(_intent_json())

    async def _run() -> None:
        async for _chunk in stream_brain_a(
            role="mira-chatter",
            prompt_md_path="interviewer_brain_a.md",
            transcript_tail=[],
            brain_b_intent=intent,
            persona="",
            router=router,
        ):
            pass

    asyncio.run(_run())

    request = router.calls[0]
    extra_body = request.get("extra_body") or {}
    chat_template_kwargs = extra_body.get("chat_template_kwargs") or {}
    assert chat_template_kwargs.get("enable_thinking") is False
    assert request["max_tokens"] >= 4096


def test_brain_a_request_threads_chatter_temperature() -> None:
    """Chatter resolution carries a per-brain temperature; Brain A must apply it."""
    router = _BrainAStreamRouter()
    intent = BrainBIntent.model_validate_json(_intent_json())

    async def _run() -> None:
        async for _chunk in stream_brain_a(
            role="mira-chatter",
            prompt_md_path="interviewer_brain_a.md",
            transcript_tail=[],
            brain_b_intent=intent,
            persona="",
            router=router,
            catalog_resolution=_chatter_resolution(temperature=0.7),
        ):
            pass

    asyncio.run(_run())

    request = router.calls[0]
    assert request.get("temperature") == 0.7


def test_brain_b_request_threads_scientist_temperature() -> None:
    """Scientist resolution carries a per-brain temperature; Brain B must apply it."""
    router = _BrainBRouter()

    async def _run() -> None:
        await run_brain_b_with_tools(
            surface="interviewer",
            system_context=[],
            transcript_tail=[],
            registry=ToolRegistry([]),
            router=router,
            rubric_axes=[],
            catalog_resolution=_scientist_resolution(mode="on", temperature=0.3),
        )

    asyncio.run(_run())

    request = router.calls[0]
    assert request.get("temperature") == 0.3


def test_seed_entries_clamps_scientist_reasoning_off_when_unsupported(monkeypatch) -> None:
    """When the deployed scientist model does not support reasoning, the
    catalog must clamp scientist + analyst reasoning_mode to ``off``.

    Without the clamp, a non-thinking model (Gemma, AgenticQwen, Qwen3-base)
    receives ``enable_thinking=true`` from the catalog default and produces
    thousands of tokens of stream-of-consciousness before any tool call,
    blowing per-turn latency past the participant pacing window.
    """
    from agentic_survey.config import get_settings
    from agentic_survey.llm.catalog import seed_entries

    monkeypatch.setenv("SURVEY_SCIENTIST_SUPPORTS_REASONING", "false")
    get_settings.cache_clear()  # reload settings under patched env

    entries = {entry.role: entry for entry in seed_entries()}
    assert entries["scientist"].reasoning_mode == "off"
    assert entries["analyst"].reasoning_mode == "off"
    # Validator and ingest were already off; chatter is always off.
    assert entries["validator"].reasoning_mode == "off"
    assert entries["ingest"].reasoning_mode == "off"
    assert entries["chatter"].reasoning_mode == "off"

    get_settings.cache_clear()


def test_seed_entries_keeps_scientist_reasoning_on_when_supported(monkeypatch) -> None:
    """The clamp is gated on the env var; the default behavior is reasoning-on
    so dual-machine deploys with Nemotron OMNI on the scientist endpoint keep
    their thinking budget."""
    from agentic_survey.config import get_settings
    from agentic_survey.llm.catalog import seed_entries

    monkeypatch.setenv("SURVEY_SCIENTIST_SUPPORTS_REASONING", "true")
    get_settings.cache_clear()

    entries = {entry.role: entry for entry in seed_entries()}
    assert entries["scientist"].reasoning_mode == "on"
    assert entries["analyst"].reasoning_mode == "on"

    get_settings.cache_clear()


def test_seed_entries_threads_per_brain_temperatures(monkeypatch) -> None:
    """seed_entries reads chatter/scientist temperatures from settings and
    sets them on each catalog entry. Validator and ingest stay deterministic
    at 0.0 regardless of the scientist temperature; embedding has no
    temperature."""
    from agentic_survey.config import get_settings
    from agentic_survey.llm.catalog import seed_entries

    monkeypatch.setenv("SURVEY_CHATTER_TEMPERATURE", "0.85")
    monkeypatch.setenv("SURVEY_SCIENTIST_TEMPERATURE", "0.25")
    get_settings.cache_clear()

    entries = {entry.role: entry for entry in seed_entries()}
    assert entries["chatter"].temperature == 0.85
    assert entries["scientist"].temperature == 0.25
    assert entries["analyst"].temperature == 0.25
    assert entries["validator"].temperature == 0.0
    assert entries["ingest"].temperature == 0.0
    assert entries["embedding"].temperature is None

    get_settings.cache_clear()
