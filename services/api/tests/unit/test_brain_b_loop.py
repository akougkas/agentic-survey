from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from agentic_survey.agents.brain_b_loop import (
    BrainBLoopError,
    BrainBToolBudgetExceeded,
    run_brain_b_with_tools,
)
from agentic_survey.agents.tools.definitions import (
    get_outline_state_tool,
    search_knowledge_tool,
)
from agentic_survey.agents.tools.registry import (
    MiraTool,
    ToolDispatchError,
    ToolRegistry,
)
from agentic_survey.domain.outline import OutlineArtifact


class _ScriptedRouter:
    """Returns pre-scripted completion payloads in order, one per acompletion call."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def acompletion(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if not self._responses:
            raise RuntimeError("scripted router exhausted")
        return self._responses.pop(0)


def _intent_payload(
    *,
    question: str = "What sampling frame are we committed to?",
    options: list[str] | None = None,
    should_close: bool = False,
) -> dict[str, Any]:
    final_options = options if options is not None else [
        "Inclusion by role",
        "Inclusion by workflow",
        "Inclusion by tenure",
        "Discuss this more.",
    ]
    return {
        "active_axis": "sampling_frame",
        "axes_coverage": [],
        "question_intent": "clarify",
        "get_user_input": {
            "question": question,
            "options": final_options,
            "allow_free_text": True,
        },
        "outline_patch": None,
        "ready_for_review": False,
        "should_close": should_close,
        "closing": False,
        "retrieval_used": False,
        "retrieval_chunks": [],
    }


def _completion(*, content: str | None = None, tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"content": content, "tool_calls": tool_calls}
    return {"choices": [{"message": message}]}


def _tool_call(*, call_id: str, name: str, arguments: dict[str, Any] | str) -> dict[str, Any]:
    args_str = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": args_str},
    }


def _noop_search():
    async def _handler(query: str, k: int) -> list[dict[str, Any]]:
        return []

    return _handler


def _outline() -> OutlineArtifact:
    return OutlineArtifact(
        research_question="Does trust calibration separate durable AI adopters from churners?",
        sampling_frame="Domain scientists with two years of tool use.",
    )


def _registry_with_search(results: list[dict[str, Any]]) -> ToolRegistry:
    captured: list[tuple[str, int]] = []

    async def search(query: str, k: int, mode: str = "hybrid") -> list[dict[str, Any]]:
        captured.append((query, k))
        return results

    registry = ToolRegistry(
        [
            search_knowledge_tool(search_fn=search),
            get_outline_state_tool(outline_provider=_outline),
        ]
    )
    setattr(registry, "_captured", captured)
    return registry


def test_single_turn_no_tool_calls_returns_intent() -> None:
    router = _ScriptedRouter([_completion(content=json.dumps(_intent_payload()))])
    registry = ToolRegistry()
    result = asyncio.run(
        run_brain_b_with_tools(
            surface="designer",
            system_context=["Outline: {}"],
            transcript_tail=[{"role": "user", "content": "let's start"}],
            registry=registry,
            router=router,
        )
    )
    assert result.intent.get_user_input.options[-1] == "Discuss this more."
    assert result.tool_calls == []
    assert result.intent.retrieval_used is False
    assert len(router.calls) == 1
    # No tools registered: the completion must not have been asked for any.
    assert "tools" not in router.calls[0] or not router.calls[0].get("tools")


def test_single_tool_call_then_terminal_intent() -> None:
    results = [{"chunk_id": "chunk_42", "score": 0.91, "content": "saturation heuristic"}]
    registry = _registry_with_search(results)
    router = _ScriptedRouter(
        [
            _completion(
                tool_calls=[
                    _tool_call(
                        call_id="call_0",
                        name="search_knowledge",
                        arguments={"query": "saturation heuristic", "k": 3},
                    )
                ]
            ),
            _completion(content=json.dumps(_intent_payload())),
        ]
    )
    result = asyncio.run(
        run_brain_b_with_tools(
            surface="designer",
            system_context=[],
            transcript_tail=[{"role": "user", "content": "when is saturation reached?"}],
            registry=registry,
            router=router,
        )
    )
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "search_knowledge"
    assert result.tool_calls[0].result == results
    assert result.intent.retrieval_used is True
    assert result.intent.retrieval_chunks == ["chunk_42"]


def test_tool_call_budget_exceeded_raises() -> None:
    registry = _registry_with_search([])
    # Script three back-to-back tool-call responses; budget of 2 should abort.
    router = _ScriptedRouter(
        [
            _completion(
                tool_calls=[
                    _tool_call(call_id="c1", name="search_knowledge", arguments={"query": "a", "k": 3})
                ]
            ),
            _completion(
                tool_calls=[
                    _tool_call(call_id="c2", name="search_knowledge", arguments={"query": "b", "k": 3}),
                    _tool_call(call_id="c3", name="search_knowledge", arguments={"query": "c", "k": 3}),
                ]
            ),
        ]
    )
    with pytest.raises(BrainBToolBudgetExceeded):
        asyncio.run(
            run_brain_b_with_tools(
                surface="designer",
                system_context=[],
                transcript_tail=[],
                registry=registry,
                router=router,
                max_tool_calls=2,
            )
        )


def test_parse_retry_recovers_on_second_attempt() -> None:
    broken = "{not json"
    fixed = json.dumps(_intent_payload())
    router = _ScriptedRouter(
        [
            _completion(content=broken),
            _completion(content=fixed),
        ]
    )
    result = asyncio.run(
        run_brain_b_with_tools(
            surface="designer",
            system_context=[],
            transcript_tail=[],
            registry=ToolRegistry(),
            router=router,
        )
    )
    assert result.intent.get_user_input.options[-1] == "Discuss this more."
    assert len(router.calls) == 2


def test_parse_failure_beyond_retry_budget_raises() -> None:
    broken = "still not json"
    router = _ScriptedRouter(
        [
            _completion(content=broken),
            _completion(content=broken),
        ]
    )
    with pytest.raises(BrainBLoopError) as excinfo:
        asyncio.run(
            run_brain_b_with_tools(
                surface="designer",
                system_context=[],
                transcript_tail=[],
                registry=ToolRegistry(),
                router=router,
            )
        )
    assert excinfo.value.raw_output == broken


def test_discuss_more_normalizer_appends_missing_option() -> None:
    payload = _intent_payload(
        options=["Focus the research question", "Name two disconfirmers", "Add a probe"]
    )
    router = _ScriptedRouter([_completion(content=json.dumps(payload))])
    result = asyncio.run(
        run_brain_b_with_tools(
            surface="designer",
            system_context=[],
            transcript_tail=[],
            registry=ToolRegistry(),
            router=router,
        )
    )
    assert result.intent.get_user_input.options[-1] == "Discuss this more."
    assert len(result.intent.get_user_input.options) == 4


def test_tool_registry_rejects_duplicate_names() -> None:
    async def handler(_args: dict[str, Any]) -> dict[str, Any]:
        return {}

    tool = MiraTool(
        name="dupe",
        description="d",
        parameters_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=handler,
    )
    registry = ToolRegistry([tool])
    with pytest.raises(ValueError):
        registry.register(tool)


def test_tool_dispatch_surfaces_handler_errors_as_tool_messages() -> None:
    async def boom(query: str, k: int, mode: str = "hybrid") -> list[dict[str, Any]]:
        raise RuntimeError("retrieval backend unavailable")

    registry = ToolRegistry([search_knowledge_tool(search_fn=boom)])
    router = _ScriptedRouter(
        [
            _completion(
                tool_calls=[
                    _tool_call(
                        call_id="c1",
                        name="search_knowledge",
                        arguments={"query": "anything", "k": 3},
                    )
                ]
            ),
            _completion(content=json.dumps(_intent_payload())),
        ]
    )
    result = asyncio.run(
        run_brain_b_with_tools(
            surface="designer",
            system_context=[],
            transcript_tail=[],
            registry=registry,
            router=router,
        )
    )
    # Error is captured in the tool_call record, loop recovers, intent lands.
    assert len(result.tool_calls) == 1
    assert "retrieval backend unavailable" in str(result.tool_calls[0].result)
    assert result.intent.retrieval_used is True


def test_unknown_tool_name_raises_in_registry() -> None:
    registry = ToolRegistry()
    with pytest.raises(ToolDispatchError):
        asyncio.run(registry.dispatch("nonexistent", "{}"))


def test_malformed_tool_arguments_raise_in_registry() -> None:
    async def search(query: str, k: int, mode: str = "hybrid") -> list[dict[str, Any]]:
        return []

    registry = ToolRegistry([search_knowledge_tool(search_fn=search)])
    with pytest.raises(ToolDispatchError):
        asyncio.run(registry.dispatch("search_knowledge", "{not json"))
