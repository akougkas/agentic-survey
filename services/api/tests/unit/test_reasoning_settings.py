from __future__ import annotations

import asyncio

from agentic_survey.llm.catalog import CatalogResolution, seed_entries
from agentic_survey.llm.client import ChatMessage, LLMClient
from agentic_survey.llm.pool import AgentRole, EndpointConfig
from agentic_survey.llm.reasoning import (
    REPAIR_COMPLETION_TOKENS,
    VISIBLE_REPLY_MAX_TOKENS,
    apply_reasoning_settings,
    reasoning_completion_tokens,
    reasoning_final_response_tokens,
    set_lmstudio_thinking,
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
        return self.get_endpoint("dynamo" if role is not AgentRole.DESIGNER else "mini")


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


def _resolution(
    *,
    mode: str,
    budget: int | None = None,
) -> CatalogResolution:
    return CatalogResolution(
        role="scientist",
        source="catalog_default",
        catalog_id="dynamo-scientist",
        endpoint="dynamo",
        model_id="nvidia-nemotron-3-nano-omni-30b-a3b-reasoning",
        api_base="http://dynamo:1234/v1",
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


def test_visible_reply_requests_disable_thinking() -> None:
    request = {"max_tokens": VISIBLE_REPLY_MAX_TOKENS}

    set_lmstudio_thinking(request, enabled=False)

    assert request["max_tokens"] == VISIBLE_REPLY_MAX_TOKENS
    assert request["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


def test_validator_catalog_default_disables_thinking() -> None:
    validator = next(
        entry
        for entry in seed_entries()
        if entry.catalog_id == "dynamo-validator"
    )
    request = {"max_tokens": 1024}

    apply_reasoning_settings(
        CatalogResolution(
            role=validator.role,
            source="catalog_default",
            catalog_id=validator.catalog_id,
            endpoint=validator.endpoint,
            model_id=validator.model_id,
            api_base="http://dynamo:1234/v1",
            reasoning_mode=validator.reasoning_mode,
            reasoning_budget_tokens=validator.reasoning_budget_tokens,
            reasoning_kwarg=validator.reasoning_kwarg,
        ),
        request,
    )

    assert request["max_tokens"] == 1024
    assert request["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


def test_repair_budget_is_smaller_than_reasoning_budget() -> None:
    assert VISIBLE_REPLY_MAX_TOKENS < REPAIR_COMPLETION_TOKENS
    assert REPAIR_COMPLETION_TOKENS < reasoning_completion_tokens()


def test_empty_content_repair_disables_reasoning() -> None:
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
    assert router.calls[1]["max_tokens"] == REPAIR_COMPLETION_TOKENS
    assert router.calls[1]["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
