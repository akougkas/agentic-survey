from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from agentic_survey.agents.brain_b_loop import (
    BrainBLoopError,
    BrainBToolBudgetExceeded,
    _apply_closing_prose_guard,
    _floor_active_axis,
    _force_axis_rotation,
    _question_intent_is_axis_label,
    run_brain_b_with_tools,
)
from agentic_survey.llm.reasoning import TrailingAssistantRoleError
from agentic_survey.llm.reasoning import repair_completion_tokens
from agentic_survey.domain.intent import (
    AxisCoverage,
    BrainBIntent,
    QuestionCoverage,
)
from agentic_survey.domain.tools import GetUserInputOptions
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


def _tool_names(call_kwargs: dict[str, Any]) -> list[str]:
    return [tool["function"]["name"] for tool in call_kwargs.get("tools", [])]


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
    # Brain B always exposes its final handoff as a structured output tool.
    tool_names = [
        tool["function"]["name"]
        for tool in router.calls[0].get("tools", [])
    ]
    assert tool_names == ["emit_brain_b_intent"]


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
    assert _tool_names(router.calls[0]) == [
        "search_knowledge",
        "get_outline_state",
    ]
    assert "tool_choice" not in router.calls[0]
    assert _tool_names(router.calls[1]) == ["emit_brain_b_intent"]
    assert router.calls[1]["tool_choice"] == {
        "type": "function",
        "function": {"name": "emit_brain_b_intent"},
    }


def test_output_tool_call_returns_intent_without_response_format() -> None:
    payload = _intent_payload()
    router = _ScriptedRouter(
        [
            _completion(
                tool_calls=[
                    _tool_call(
                        call_id="final",
                        name="emit_brain_b_intent",
                        arguments=payload,
                    )
                ]
            )
        ]
    )
    result = asyncio.run(
        run_brain_b_with_tools(
            surface="interviewer",
            system_context=[],
            transcript_tail=[{"role": "user", "content": "What happened in staging?"}],
            registry=ToolRegistry(),
            router=router,
        )
    )
    assert result.intent.get_user_input.question == payload["get_user_input"]["question"]
    assert result.tool_calls == []
    assert "response_format" not in router.calls[0]
    assert _tool_names(router.calls[0]) == ["emit_brain_b_intent"]
    assert router.calls[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "emit_brain_b_intent"},
    }


def test_registry_tools_run_before_same_message_output_tool() -> None:
    results = [{"chunk_id": "chunk_99", "score": 0.8, "content": "staging friction"}]
    registry = _registry_with_search(results)
    early_payload = _intent_payload(question="This output should be deferred.")
    final_payload = _intent_payload(question="What made staging fragile?")
    router = _ScriptedRouter(
        [
            _completion(
                tool_calls=[
                    _tool_call(
                        call_id="search",
                        name="search_knowledge",
                        arguments={"query": "staging friction", "k": 3},
                    ),
                    _tool_call(
                        call_id="final-too-early",
                        name="emit_brain_b_intent",
                        arguments=early_payload,
                    ),
                ]
            ),
            _completion(
                tool_calls=[
                    _tool_call(
                        call_id="final",
                        name="emit_brain_b_intent",
                        arguments=final_payload,
                    )
                ]
            ),
        ]
    )

    result = asyncio.run(
        run_brain_b_with_tools(
            surface="interviewer",
            system_context=[],
            transcript_tail=[{"role": "user", "content": "staging was fragile"}],
            registry=registry,
            router=router,
        )
    )

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "search_knowledge"
    assert result.intent.get_user_input.question == "What made staging fragile?"
    assert result.intent.retrieval_used is True
    assert result.intent.retrieval_chunks == ["chunk_99"]


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
    assert _tool_names(router.calls[0]) == ["emit_brain_b_intent"]
    assert router.calls[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "emit_brain_b_intent"},
    }
    assert "validation_error" in router.calls[1]["messages"][-1]["content"]


def test_planning_miss_switches_to_forced_output_without_thinking() -> None:
    router = _ScriptedRouter(
        [
            _completion(content=""),
            _completion(content=json.dumps(_intent_payload())),
        ]
    )
    result = asyncio.run(
        run_brain_b_with_tools(
            surface="interviewer",
            system_context=[],
            transcript_tail=[],
            registry=_registry_with_search([]),
            router=router,
        )
    )

    assert result.intent.get_user_input.options[-1] == "Discuss this more."
    assert len(router.calls) == 2
    first_kwargs = router.calls[0]
    retry_kwargs = router.calls[1]
    assert first_kwargs["model"] == "mira-scientist"
    assert first_kwargs["tools"]
    assert first_kwargs["max_tokens"] == 384
    assert _tool_names(first_kwargs) == [
        "search_knowledge",
        "get_outline_state",
    ]
    assert "tool_choice" not in first_kwargs
    assert first_kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
    assert retry_kwargs["model"] == "mira-scientist"
    assert retry_kwargs["max_tokens"] == repair_completion_tokens()
    assert retry_kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
    assert _tool_names(retry_kwargs) == ["emit_brain_b_intent"]
    assert retry_kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "emit_brain_b_intent"},
    }


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


def test_chip_normalizer_drops_paragraph_quotes_and_dedupes() -> None:
    long_quote = (
        "The data starts at the K3 detector on the Krios microscope, lands on a "
        "buffer disk in the imaging room, and we ship it nightly to the cluster "
        "scratch via Globus. Motion correction and CTF estimation run on GPU "
        "nodes; the per-particle stacks live on /scratch for the active run."
    )
    payload = _intent_payload(
        options=[
            long_quote,
            long_quote,
            long_quote,
            "options_are_3_or_4_strings_with_last_option_literally_Discuss_this_more._,",
            "[Skip this]",
            "  ",
        ]
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
    options = result.intent.get_user_input.options
    # Cap is 4 total; at minimum the closing chip is always present.
    assert 1 <= len(options) <= 4
    assert options[-1] == "Discuss this more."
    # Schema-rule fragment must not reach the UI.
    assert all("options_are_3_or_4_strings" not in opt for opt in options)
    # Square-bracket wrapping is stripped, never displayed verbatim.
    assert all(not (opt.startswith("[") and opt.endswith("]")) for opt in options)
    # Length cap stops paragraph-quotes from leaking through; the lone
    # surviving non-discuss chip is the truncated paragraph-quote.
    for opt in options[:-1]:
        assert len(opt) <= 120
    # Duplicates collapse to a single entry plus the closing chip.
    paragraph_chips = [opt for opt in options if opt != "Discuss this more."]
    assert len({chip.lower() for chip in paragraph_chips}) == len(paragraph_chips)


def test_brain_b_summary_log_includes_search_queries_and_axes(caplog) -> None:
    payload = _intent_payload()
    router = _ScriptedRouter(
        [
            _completion(
                tool_calls=[
                    _tool_call(
                        call_id="c1",
                        name="search_knowledge",
                        arguments={"query": "scientific data lifecycle phases", "k": 3},
                    )
                ]
            ),
            _completion(content=json.dumps(payload)),
        ]
    )

    async def _search(query: str, k: int, mode: str = "hybrid") -> list[dict[str, Any]]:
        return [{"chunk_id": "kc1", "score": 0.5}]

    registry = ToolRegistry([search_knowledge_tool(search_fn=_search)])
    with caplog.at_level("WARNING", logger="agentic_survey.agents.brain_b_loop"):
        asyncio.run(
            run_brain_b_with_tools(
                surface="interviewer",
                system_context=[],
                transcript_tail=[],
                registry=registry,
                router=router,
            )
        )
    summary_lines = [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("brain_b_summary")
    ]
    assert summary_lines, "brain_b_summary line missing from WARNING log"
    body = json.loads(summary_lines[0].split(" ", 1)[1])
    assert body["surface"] == "interviewer"
    assert body["tool_calls_count"] == 1
    assert body["search_queries"] == ["scientific data lifecycle phases"]
    assert body["retrieval_used"] is True
    assert "search_knowledge" in body["tool_names"]


def test_chip_grounding_drops_abstract_chips_when_corpus_present() -> None:
    """Chips with zero overlap with the participant's last turn are dropped.

    Reproduces session-C turn-2 where the participant told a concrete dataset-
    versioning story (data-corpus v0.4.2 vs v0.4.3, three re-tokenized tasks)
    but Mira's chips were generic architecture phrases ("modular pipeline",
    "shared data catalog", "event-driven workflow engine"). The grounding
    filter drops the generic chips and lets the concrete one through.
    """
    payload = _intent_payload(
        options=[
            "Begin with a modular pipeline approach",
            "Use a shared data catalog for everyone",
            "Pin checkpoints to dataset version v0.4.2",
        ]
    )
    router = _ScriptedRouter([_completion(content=json.dumps(payload))])
    result = asyncio.run(
        run_brain_b_with_tools(
            surface="interviewer",
            system_context=[],
            transcript_tail=[],
            registry=ToolRegistry(),
            router=router,
            last_participant_message=(
                "We had a v0.4.2 dataset that re-tokenized into v0.4.3 and broke "
                "three checkpoints downstream."
            ),
            participant_extracted_concepts=[
                "dataset version",
                "checkpoint",
                "re-tokenize",
            ],
        )
    )
    options = result.intent.get_user_input.options
    assert "Pin checkpoints to dataset version v0.4.2" in options
    assert all("modular pipeline" not in opt.lower() for opt in options)
    assert all("shared data catalog" not in opt.lower() for opt in options)
    assert options[-1] == "Discuss this more."


def test_chip_grounding_passes_through_when_corpus_empty() -> None:
    """Cold start: no participant turn yet → grounding filter is permissive."""
    payload = _intent_payload(
        options=[
            "An anchor about modular pipelines",
            "An anchor about event-driven flow",
            "An anchor about shared catalogs",
        ]
    )
    router = _ScriptedRouter([_completion(content=json.dumps(payload))])
    result = asyncio.run(
        run_brain_b_with_tools(
            surface="interviewer",
            system_context=[],
            transcript_tail=[],
            registry=ToolRegistry(),
            router=router,
            last_participant_message="",
            participant_extracted_concepts=None,
        )
    )
    options = result.intent.get_user_input.options
    # All three abstract chips survive when corpus is empty.
    assert len(options) == 4
    assert options[-1] == "Discuss this more."


def test_chip_grounding_keeps_one_anchor_when_filter_kills_everything() -> None:
    """Filter dropping every chip would shrink options below the schema minimum.
    The fallback path keeps one ungrounded anchor so the schema stays valid.
    """
    payload = _intent_payload(
        options=[
            "An abstract pattern about modular pipelines",
            "An abstract architecture for shared catalogs",
            "An abstract event-driven workflow engine",
        ]
    )
    router = _ScriptedRouter([_completion(content=json.dumps(payload))])
    result = asyncio.run(
        run_brain_b_with_tools(
            surface="interviewer",
            system_context=[],
            transcript_tail=[],
            registry=ToolRegistry(),
            router=router,
            last_participant_message="Lustre Globus cryoSPARC TRPV1 cryo-EM",
            participant_extracted_concepts=["Lustre", "Globus"],
        )
    )
    options = result.intent.get_user_input.options
    assert len(options) == 2
    assert options[-1] == "Discuss this more."


def test_chip_grounding_concept_label_match_is_phrase_aware() -> None:
    """Multi-word concept labels match a chip that contains the same phrase."""
    payload = _intent_payload(
        options=[
            "Use the Lustre filesystem during staging",
            "Skip the Globus pull entirely",
            "Add an unrelated decoration to the monitor",
        ]
    )
    router = _ScriptedRouter([_completion(content=json.dumps(payload))])
    result = asyncio.run(
        run_brain_b_with_tools(
            surface="interviewer",
            system_context=[],
            transcript_tail=[],
            registry=ToolRegistry(),
            router=router,
            last_participant_message="staging via Globus into the cluster scratch",
            participant_extracted_concepts=["Lustre filesystem", "Globus"],
        )
    )
    options = result.intent.get_user_input.options
    assert "Use the Lustre filesystem during staging" in options
    assert "Skip the Globus pull entirely" in options
    assert all("decoration" not in opt.lower() for opt in options)


def test_chip_normalizer_caps_total_options_at_four() -> None:
    payload = _intent_payload(
        options=[
            "First anchor episode",
            "Second anchor episode",
            "Third anchor episode",
            "Fourth anchor episode",
            "Fifth anchor episode",
        ]
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
    options = result.intent.get_user_input.options
    assert len(options) == 4
    assert options[-1] == "Discuss this more."


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


def test_unknown_tool_call_in_loop_is_dropped_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``get_user_input`` is the JSON output contract, not a callable tool.

    OMNI occasionally emits a tool_call for it. The loop must log a
    warning and drop the call so the turn proceeds on whatever content
    is also available, with the parse-retry path covering a stub model
    that emits no content.
    """
    registry = _registry_with_search(results=[])
    router = _ScriptedRouter(
        [
            # First model response: ONLY a bogus tool_call, no content.
            _completion(
                tool_calls=[
                    _tool_call(
                        call_id="c-bogus",
                        name="get_user_input",
                        arguments={"question": "anything"},
                    )
                ]
            ),
            # Second iteration: parse-retry kicks in (terminal_only path)
            # and the model finally emits a proper intent.
            _completion(content=json.dumps(_intent_payload())),
        ]
    )

    caplog.set_level("WARNING", logger="agentic_survey.agents.brain_b_loop")
    result = asyncio.run(
        run_brain_b_with_tools(
            surface="interviewer",
            system_context=[],
            transcript_tail=[],
            registry=registry,
            router=router,
        )
    )

    assert result.tool_calls == []
    assert result.intent.active_axis == "sampling_frame"
    bogus_warnings = [
        record for record in caplog.records if "get_user_input" in record.getMessage()
    ]
    assert bogus_warnings, "expected a warning about the dropped get_user_input tool call"
    assert any(
        "dropped unknown tool_call" in record.getMessage() for record in bogus_warnings
    )


def test_malformed_tool_arguments_raise_in_registry() -> None:
    async def search(query: str, k: int, mode: str = "hybrid") -> list[dict[str, Any]]:
        return []

    registry = ToolRegistry([search_knowledge_tool(search_fn=search)])
    with pytest.raises(ToolDispatchError):
        asyncio.run(registry.dispatch("search_knowledge", "{not json"))


def _build_intent(
    *,
    active_axis: str = "R1",
    axes: list[tuple[str, float]] | None = None,
    question_intent: str = "operational intent text",
    retrieval_used: bool = False,
    question_coverage: list[QuestionCoverage] | None = None,
) -> BrainBIntent:
    axes_payload = axes if axes is not None else [("R1", 0.0), ("R2", 0.0)]
    return BrainBIntent(
        active_axis=active_axis,
        axes_coverage=[AxisCoverage(axis=prefix, score=score) for prefix, score in axes_payload],
        question_coverage=question_coverage or [],
        question_intent=question_intent,
        get_user_input=GetUserInputOptions(
            question="What happened most recently?",
            options=["A", "B", "C", "Discuss this more."],
            allow_free_text=True,
        ),
        retrieval_used=retrieval_used,
    )


def test_floor_active_axis_bumps_zero_on_retrieval_turn() -> None:
    intent = _build_intent(
        active_axis="R1 — Lifecycle pain topology",
        axes=[("R1", 0.0), ("R2", 0.0)],
        retrieval_used=True,
    )
    bumped = _floor_active_axis(intent, rubric_axes=["R1 — Lifecycle pain topology", "R2 — Other"])
    scores = {entry.axis: entry.score for entry in bumped.axes_coverage}
    assert scores["R1"] == pytest.approx(0.20)
    assert scores["R2"] == 0.0


def test_floor_active_axis_bumps_when_question_advanced_to_partial() -> None:
    intent = _build_intent(
        active_axis="R1",
        axes=[("R1", 0.0)],
        retrieval_used=False,
        question_coverage=[QuestionCoverage(question_id="A-Q7", status="partial", confidence=0.5)],
    )
    bumped = _floor_active_axis(intent, rubric_axes=["R1 — Lifecycle"])
    assert bumped.axes_coverage[0].score == pytest.approx(0.20)


def test_floor_active_axis_preserves_existing_positive_score() -> None:
    intent = _build_intent(
        active_axis="R1",
        axes=[("R1", 0.55), ("R2", 0.0)],
        retrieval_used=True,
    )
    bumped = _floor_active_axis(intent, rubric_axes=["R1 — A", "R2 — B"])
    scores = {entry.axis: entry.score for entry in bumped.axes_coverage}
    assert scores["R1"] == pytest.approx(0.55)
    assert scores["R2"] == 0.0


def test_floor_active_axis_skips_non_substantive_turn() -> None:
    intent = _build_intent(
        active_axis="R1",
        axes=[("R1", 0.0), ("R2", 0.0)],
        retrieval_used=False,
        question_coverage=[QuestionCoverage(question_id="A-Q7", status="targeting", confidence=0.0)],
    )
    bumped = _floor_active_axis(intent, rubric_axes=["R1 — A", "R2 — B"])
    assert bumped.axes_coverage[0].score == 0.0
    assert bumped.axes_coverage[1].score == 0.0


def test_floor_active_axis_skips_active_axis_outside_rubric() -> None:
    intent = _build_intent(
        active_axis="R9",
        axes=[("R1", 0.0)],
        retrieval_used=True,
    )
    bumped = _floor_active_axis(intent, rubric_axes=["R1 — A"])
    assert bumped.axes_coverage[0].score == 0.0


def test_question_intent_is_axis_label_detects_bare_prefix() -> None:
    assert _question_intent_is_axis_label(
        "R1",
        active_prefix="R1",
        rubric_axes=["R1 — Lifecycle pain topology"],
    )


def test_question_intent_is_axis_label_detects_full_label() -> None:
    assert _question_intent_is_axis_label(
        "R1 — Lifecycle pain topology",
        active_prefix="R1",
        rubric_axes=["R1 — Lifecycle pain topology"],
    )


def test_question_intent_is_axis_label_detects_full_label_with_description() -> None:
    full = "R1 — Lifecycle pain topology: where friction concentrates per phase"
    assert _question_intent_is_axis_label(
        full,
        active_prefix="R1",
        rubric_axes=[full],
    )


def test_question_intent_is_axis_label_passes_operational_sentence() -> None:
    operational = "R1: Where in your last cryo-EM run did staging cost you the most time?"
    assert not _question_intent_is_axis_label(
        operational,
        active_prefix="R1",
        rubric_axes=["R1 — Lifecycle pain topology"],
    )


def test_force_axis_rotation_overrides_third_consecutive_turn() -> None:
    """Two prior R1 turns, model emits R1 again — orchestrator rotates to R2."""
    intent = _build_intent(
        active_axis="R1 — Lifecycle pain topology",
        axes=[("R1", 0.20), ("R2", 0.0), ("R3", 0.0)],
    )
    rotated, fired = _force_axis_rotation(
        intent,
        rubric_axes=[
            "R1 — Lifecycle pain topology",
            "R2 — Tooling exposure",
            "R3 — Handoffs",
        ],
        prior_active_axis_prefix="R1",
        prior_consecutive_count=2,
        surface="interviewer",
    )
    assert fired is True
    assert rotated.active_axis == "R2 — Tooling exposure"


def test_force_axis_rotation_skips_when_under_budget() -> None:
    """Only one prior turn on R1; orchestrator must not rotate yet."""
    intent = _build_intent(
        active_axis="R1",
        axes=[("R1", 0.20), ("R2", 0.0)],
    )
    rotated, fired = _force_axis_rotation(
        intent,
        rubric_axes=["R1 — A", "R2 — B"],
        prior_active_axis_prefix="R1",
        prior_consecutive_count=1,
        surface="interviewer",
    )
    assert fired is False
    assert rotated.active_axis == "R1"


def test_force_axis_rotation_skips_when_model_already_rotated() -> None:
    """Two prior R1 turns, but model emits R3 itself — orchestrator stays out."""
    intent = _build_intent(
        active_axis="R3 — Handoffs",
        axes=[("R1", 0.20), ("R2", 0.0), ("R3", 0.0)],
    )
    rotated, fired = _force_axis_rotation(
        intent,
        rubric_axes=["R1 — A", "R2 — B", "R3 — Handoffs"],
        prior_active_axis_prefix="R1",
        prior_consecutive_count=3,
        surface="interviewer",
    )
    assert fired is False
    assert rotated.active_axis == "R3 — Handoffs"


def test_force_axis_rotation_skips_when_no_unfired_axis_available() -> None:
    """Every rubric axis already has positive score; nothing to rotate to."""
    intent = _build_intent(
        active_axis="R1",
        axes=[("R1", 0.55), ("R2", 0.30)],
    )
    rotated, fired = _force_axis_rotation(
        intent,
        rubric_axes=["R1 — A", "R2 — B"],
        prior_active_axis_prefix="R1",
        prior_consecutive_count=4,
        surface="interviewer",
    )
    assert fired is False
    assert rotated.active_axis == "R1"


def test_force_axis_rotation_picks_lowest_numbered_unfired_axis() -> None:
    """R1 saturated, R2 fired-but-low, R3 still 0.0 — orchestrator picks R3
    when prior axis was R2 and R3 is the lowest-numbered axis at 0.0."""
    intent = _build_intent(
        active_axis="R2",
        axes=[("R1", 0.45), ("R2", 0.20), ("R3", 0.0), ("R4", 0.0)],
    )
    rotated, fired = _force_axis_rotation(
        intent,
        rubric_axes=["R1 — A", "R2 — B", "R3 — C", "R4 — D"],
        prior_active_axis_prefix="R2",
        prior_consecutive_count=2,
        surface="interviewer",
    )
    assert fired is True
    assert rotated.active_axis == "R3 — C"


def test_axis_rotation_after_two_consecutive_turns_on_same_axis() -> None:
    """End-to-end: prior_consecutive=2, model emits R1 third time → orchestrator rotates.

    Acceptance criterion called out in the Phase 1.1 plan. Exercises the
    forced rotation path through the full ``run_brain_b_with_tools`` loop
    with rubric_axes wired and a scripted Brain B emission that camps on
    the prior active axis.
    """
    payload = {
        "active_axis": "R1",
        "axes_coverage": [
            {"axis": "R1", "score": 0.20},
            {"axis": "R2", "score": 0.0},
            {"axis": "R3", "score": 0.0},
        ],
        "question_coverage": [],
        "question_intent": "R1: another R1 probe",
        "get_user_input": {
            "question": "Tell me more about that staging step.",
            "options": ["Lustre staging", "Globus pull", "ChimeraX export", "Discuss this more."],
            "allow_free_text": True,
        },
        "outline_patch": None,
        "ready_for_review": False,
        "should_close": False,
        "closing": False,
        "retrieval_used": False,
        "retrieval_chunks": [],
    }
    router = _ScriptedRouter([_completion(content=json.dumps(payload))])
    result = asyncio.run(
        run_brain_b_with_tools(
            surface="interviewer",
            system_context=[],
            transcript_tail=[],
            registry=ToolRegistry(),
            router=router,
            rubric_axes=[
                "R1 — Lifecycle pain topology",
                "R2 — Tooling exposure",
                "R3 — Handoffs",
            ],
            prior_axes_coverage=[
                AxisCoverage(axis="R1", score=0.20),
            ],
            prior_active_axis_prefix="R1",
            prior_consecutive_active_axis_count=2,
        )
    )
    intent = result.intent
    assert intent.active_axis == "R2 — Tooling exposure"
    scores = {entry.axis: entry.score for entry in intent.axes_coverage}
    assert scores["R1"] == pytest.approx(0.20)
    # Forced rotation skips the floor on the rotated axis so a fresh axis
    # is not credited with evidence from the prior axis.
    assert scores["R2"] == 0.0


def test_closing_prose_forces_should_close() -> None:
    """Brain A reply with closing language forces should_close + closing chips.

    Reproduces session-C turn-8 where Mira's prose said "I have enough to
    wrap up. Thank you for the time." but the planner intent stayed at
    should_close=False and emitted quote-back chips. The orchestrator must
    detect the drift and reconcile.
    """
    intent = _build_intent(
        active_axis="R4",
        axes=[("R4", 0.40)],
        question_intent="Quote back the participant's lineage requirement.",
    )
    reply_text = (
        "We have covered your requirements for lineage and the boundaries "
        "of where a system should stay out of the judgment layer. "
        "I have enough to wrap up. Thank you for the time."
    )
    forced = _apply_closing_prose_guard(intent, reply_text=reply_text)
    assert forced.should_close is True
    assert forced.closing is True
    assert forced.get_user_input.options == ["End conversation", "Discuss this more."]


def test_closing_prose_guard_no_op_when_already_closing() -> None:
    intent = _build_intent(
        active_axis="R4",
        axes=[("R4", 0.40)],
    )
    intent = intent.model_copy(update={"should_close": True, "closing": True})
    forced = _apply_closing_prose_guard(intent, reply_text="I have enough to wrap up")
    assert forced is intent  # idempotent: same object returned


def test_closing_prose_guard_no_op_on_substantive_reply() -> None:
    intent = _build_intent(active_axis="R1", axes=[("R1", 0.20)])
    reply_text = "Tell me more about that staging step in cryo-EM."
    forced = _apply_closing_prose_guard(intent, reply_text=reply_text)
    assert forced.should_close is False
    assert forced.get_user_input.options[-1] == "Discuss this more."


def test_closing_prose_guard_matches_thanks_phrasing() -> None:
    intent = _build_intent(active_axis="R8", axes=[("R8", 0.40)])
    reply_text = "Got it. Thanks for the time you spent on this."
    forced = _apply_closing_prose_guard(intent, reply_text=reply_text)
    assert forced.should_close is True
    assert forced.get_user_input.options == ["End conversation", "Discuss this more."]


def test_question_intent_reformation_promotes_axis_label_to_operational() -> None:
    """End-to-end: Brain B emits the rubric label; orchestrator reforms it from the question."""

    payload = {
        "active_axis": "R1",
        "axes_coverage": [{"axis": "R1", "score": 0.0}],
        "question_coverage": [],
        "question_intent": "R1 — Lifecycle pain topology",
        "get_user_input": {
            "question": "Walk me through the last time staging held up your analysis.",
            "options": ["The TRPV1 run", "The 12 TB pull", "Last quarter", "Discuss this more."],
            "allow_free_text": True,
        },
        "outline_patch": None,
        "ready_for_review": False,
        "should_close": False,
        "closing": False,
        "retrieval_used": False,
        "retrieval_chunks": [],
    }
    router = _ScriptedRouter([_completion(content=json.dumps(payload))])
    result = asyncio.run(
        run_brain_b_with_tools(
            surface="interviewer",
            system_context=[],
            transcript_tail=[],
            registry=ToolRegistry(),
            router=router,
            rubric_axes=["R1 — Lifecycle pain topology"],
        )
    )
    intent = result.intent
    assert intent.question_intent.startswith("R1: ")
    assert "staging held up your analysis" in intent.question_intent


def test_trailing_assistant_transcript_uses_non_thinking_brain_b_request() -> None:
    """Brain B avoids the thinking-prefill conflict on assistant-ended tails."""
    transcript_tail = [
        {"role": "user", "content": "Walk me through last week's run."},
        {"role": "assistant", "content": "Let's stay on the staging step. Where did time go?"},
    ]
    router = _ScriptedRouter([_completion(content=json.dumps(_intent_payload()))])
    asyncio.run(
        run_brain_b_with_tools(
            surface="interviewer",
            system_context=[],
            transcript_tail=transcript_tail,
            registry=ToolRegistry(),
            router=router,
        )
    )
    sent_messages = router.calls[0]["messages"]
    assert sent_messages[-1]["role"] == "assistant"
    assert sent_messages[-1]["content"].startswith("Let's stay on the staging step")
    extra_body = router.calls[0].get("extra_body") or {}
    chat_template_kwargs = extra_body.get("chat_template_kwargs") or {}
    assert chat_template_kwargs.get("enable_thinking") is False


def test_trailing_user_tool_or_system_message_is_passed_through_unchanged() -> None:
    """Sanitizer is a no-op when the final message is a non-assistant role.

    The transcript_tail ending on ``user`` (the common case) and the loop's
    own internal message after a tool dispatch (``role: tool``) and after a
    parse-retry nudge (``role: system``) all flow to llama-server unchanged.
    """
    base_intent = json.dumps(_intent_payload())

    for trailing in (
        {"role": "user", "content": "Here is what happened."},
        {"role": "tool", "tool_call_id": "c0", "name": "search_knowledge", "content": "[]"},
        {"role": "system", "content": "Operator note: prefer concrete probes."},
    ):
        router = _ScriptedRouter([_completion(content=base_intent)])
        asyncio.run(
            run_brain_b_with_tools(
                surface="interviewer",
                system_context=[],
                transcript_tail=[trailing],
                registry=ToolRegistry(),
                router=router,
            )
        )
        sent_messages = router.calls[0]["messages"]
        # The loop also prepends a system prompt; the trailing role we
        # supplied must remain the final entry untouched.
        assert sent_messages[-1] == trailing


def test_trailing_assistant_tool_calls_without_content_raises_typed_error() -> None:
    """Sanitizer raises TrailingAssistantRoleError on a malformed pre-dispatch payload.

    An assistant message that only carries ``tool_calls`` (no content) must
    be followed by ``role: tool`` rows from the dispatch loop. If it ever
    reaches the LLM call as the trailing message, the call would 400; the
    sanitizer surfaces a typed error instead so the CLAUDE.md
    "No silent errors" invariant holds.
    """
    transcript_tail = [
        {"role": "user", "content": "Start the call."},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c0", "type": "function", "function": {"name": "search_knowledge", "arguments": "{}"}}],
        },
    ]
    router = _ScriptedRouter([_completion(content=json.dumps(_intent_payload()))])
    with pytest.raises(TrailingAssistantRoleError):
        asyncio.run(
            run_brain_b_with_tools(
                surface="interviewer",
                system_context=[],
                transcript_tail=transcript_tail,
                registry=ToolRegistry(),
                router=router,
            )
        )
