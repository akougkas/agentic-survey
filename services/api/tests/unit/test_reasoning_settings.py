from __future__ import annotations

import asyncio
import json

from agentic_survey.llm.catalog import CatalogResolution, seed_entries
from agentic_survey.llm.client import ChatMessage, LLMClient
from agentic_survey.llm.pool import AgentRole, EndpointConfig
from agentic_survey.llm.reasoning import (
    REPAIR_COMPLETION_TOKENS,
    VISIBLE_REPLY_MAX_TOKENS,
    apply_reasoning_settings,
    extract_json_object_text,
    reasoning_completion_tokens,
    reasoning_final_response_tokens,
    set_lmstudio_thinking,
    visible_reply_max_tokens,
)
from agentic_survey.repository import InMemoryRepository


class _Pool:
    def get_endpoint(self, endpoint_name: str) -> EndpointConfig:
        return EndpointConfig(
            name=endpoint_name,
            base_url=f"http://{endpoint_name}:1234/v1",
            model="nvidia-nemotron-3-nano-omni-30b-a3b-reasoning",
        )

    def resolve_endpoint(
        self,
        role: AgentRole,
        session_id: str | None = None,
    ) -> EndpointConfig:
        return self.get_endpoint("scientist" if role is not AgentRole.DESIGNER else "chatter")


class _RepairRouter:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def acompletion(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": "thinking without final content",
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"content": "final answer"}}]}


class _ReasoningJsonRouter:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    async def acompletion(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": (
                            "Work through the constraints.\n"
                            f"{json.dumps(self.payload)}\n"
                            "The object above is the final answer."
                        ),
                    }
                }
            ]
        }


def _resolution(
    *,
    mode: str,
    budget: int | None = None,
) -> CatalogResolution:
    return CatalogResolution(
        role="scientist",
        source="catalog_default",
        catalog_id="scientist-default",
        endpoint="scientist",
        model_id="nvidia-nemotron-3-nano-omni-30b-a3b-reasoning",
        api_base="http://scientist-host:1234/v1",
        reasoning_mode=mode,  # type: ignore[arg-type]
        reasoning_budget_tokens=budget,
        reasoning_kwarg="enable_thinking",
    )


def test_reasoning_on_reserves_completion_budget() -> None:
    request = {"max_tokens": 1024}

    apply_reasoning_settings(_resolution(mode="on"), request)

    assert request["max_tokens"] == reasoning_completion_tokens()
    assert request["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True


def test_reasoning_budget_preserves_final_answer_room() -> None:
    request = {"max_tokens": 1024}
    hidden_budget = 12288

    apply_reasoning_settings(_resolution(mode="budget", budget=hidden_budget), request)

    assert request["max_tokens"] == hidden_budget + reasoning_final_response_tokens()
    assert request["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True


def test_extract_json_object_text_recovers_embedded_final_object() -> None:
    raw = (
        "Scratchpad: first consider {\"draft\": true}.\n"
        "Final answer:\n"
        "{\"active_axis\":\"R1\",\"question_intent\":\"clarify\","
        "\"get_user_input\":{\"question\":\"Q?\",\"options\":[\"A\",\"B\",\"Discuss this more.\"],"
        "\"allow_free_text\":true}}\n"
        "Done."
    )

    extracted = extract_json_object_text(
        raw,
        required_keys=("active_axis", "question_intent", "get_user_input"),
    )

    assert extracted.startswith('{"active_axis"')
    assert '"get_user_input"' in extracted


def test_visible_reply_requests_disable_thinking() -> None:
    request = {"max_tokens": VISIBLE_REPLY_MAX_TOKENS}

    set_lmstudio_thinking(request, enabled=False)

    assert request["max_tokens"] == VISIBLE_REPLY_MAX_TOKENS
    assert request["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


def test_validator_catalog_default_disables_thinking() -> None:
    validator = next(
        entry
        for entry in seed_entries()
        if entry.catalog_id == "scientist-validator"
    )
    request = {"max_tokens": 1024}

    apply_reasoning_settings(
        CatalogResolution(
            role=validator.role,
            source="catalog_default",
            catalog_id=validator.catalog_id,
            endpoint=validator.endpoint,
            model_id=validator.model_id,
            api_base="http://scientist-host:1234/v1",
            reasoning_mode=validator.reasoning_mode,
            reasoning_budget_tokens=validator.reasoning_budget_tokens,
            reasoning_kwarg=validator.reasoning_kwarg,
        ),
        request,
    )

    assert request["max_tokens"] >= visible_reply_max_tokens()
    assert request["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


def test_repair_budget_is_smaller_than_reasoning_budget() -> None:
    assert VISIBLE_REPLY_MAX_TOKENS < REPAIR_COMPLETION_TOKENS
    assert REPAIR_COMPLETION_TOKENS < reasoning_completion_tokens()


def test_empty_content_repair_disables_reasoning(monkeypatch) -> None:
    """First scientist call enables thinking (so the model has reasoning headroom);
    if it returns empty content, the repair retry disables thinking and uses the
    smaller repair budget. Requires ``SURVEY_SCIENTIST_SUPPORTS_REASONING=true``
    so the catalog actually leaves scientist reasoning_mode=on for the first call.
    """
    from agentic_survey.config import get_settings

    monkeypatch.setenv("SURVEY_SCIENTIST_SUPPORTS_REASONING", "true")
    get_settings.cache_clear()

    router = _RepairRouter()
    client = LLMClient(
        _Pool(),  # type: ignore[arg-type]
        router,  # type: ignore[arg-type]
        InMemoryRepository(),
        enabled=True,
    )

    result = asyncio.run(
        client.chat(
            AgentRole.DESIGNER,
            [ChatMessage(role="user", content="Say something final.")],
            catalog_role="scientist",
            max_tokens=1024,
        )
    )

    assert result.content == "final answer"
    assert len(router.calls) == 2
    assert router.calls[0]["max_tokens"] == reasoning_completion_tokens()
    assert router.calls[0]["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True
    assert router.calls[1]["max_tokens"] >= visible_reply_max_tokens()
    assert router.calls[1]["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False

    get_settings.cache_clear()


def test_llm_client_recovers_json_from_reasoning_content(monkeypatch) -> None:
    from agentic_survey.config import get_settings

    monkeypatch.setenv("SURVEY_SCIENTIST_SUPPORTS_REASONING", "true")
    get_settings.cache_clear()

    payload = {"coverage_score": 0.75, "follow_up_needed": False}
    router = _ReasoningJsonRouter(payload)
    client = LLMClient(
        _Pool(),  # type: ignore[arg-type]
        router,  # type: ignore[arg-type]
        InMemoryRepository(),
        enabled=True,
    )

    result = asyncio.run(
        client.chat(
            AgentRole.VALIDATOR,
            [ChatMessage(role="user", content="Return validator JSON.")],
            catalog_role="validator",
            max_tokens=1024,
        )
    )

    assert json.loads(result.content) == payload
    assert len(router.calls) == 1
    assert router.calls[0]["max_tokens"] >= visible_reply_max_tokens()
    assert router.calls[0]["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False

    get_settings.cache_clear()
