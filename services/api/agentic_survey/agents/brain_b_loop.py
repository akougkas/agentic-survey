from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from agentic_survey.agents.tools.registry import ToolDispatchError, ToolRegistry
from agentic_survey.domain.intent import BrainBIntent

__all__ = [
    "BrainBLoopError",
    "BrainBLoopResult",
    "BrainBToolBudgetExceeded",
    "ToolCallRecord",
    "run_brain_b_with_tools",
]

logger = logging.getLogger(__name__)

Surface = Literal["designer", "interviewer"]
_PROMPTS_DIR = Path(__file__).with_name("prompts")
_DISCUSS_MORE = "Discuss this more."
_RESULT_LOG_LIMIT = 240


class BrainBLoopError(RuntimeError):
    """Raised when the tool-calling loop cannot produce a valid BrainBIntent."""

    def __init__(
        self,
        message: str,
        *,
        raw_output: str = "",
        surface: Surface = "designer",
    ) -> None:
        super().__init__(message)
        self.raw_output = raw_output
        self.surface = surface


class BrainBToolBudgetExceeded(BrainBLoopError):
    """Raised when Brain B issues more tool calls than ``max_tool_calls`` permits."""


@dataclass(slots=True)
class ToolCallRecord:
    """One observed tool invocation during the loop.

    ``result`` is the unclipped handler return value so downstream audit has
    full fidelity. ``result_summary`` is a truncated display form for logs.
    """

    name: str
    arguments: dict[str, Any]
    result: Any
    result_summary: str


@dataclass(slots=True)
class BrainBLoopResult:
    intent: BrainBIntent
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    raw_output: str = ""


def _brain_b_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "brain_b_intent",
            "schema": BrainBIntent.model_json_schema(),
        },
    }


def _normalize_discuss_more(raw: str) -> str:
    """Force ``get_user_input.options`` to end with exactly 'Discuss this more.'.

    Local models sometimes skip the verbatim contract. We dedupe a trailing
    match, truncate to four options, and append the canonical string. If the
    payload is not parseable JSON the text flows through unchanged so the
    caller's ValidationError diagnostics stay intact.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    gui = payload.get("get_user_input")
    if not isinstance(gui, dict):
        return raw
    options = gui.get("options")
    if not isinstance(options, list) or not options:
        return raw
    cleaned = [str(opt).strip() for opt in options if str(opt).strip()]
    cleaned = [opt for opt in cleaned if opt.lower() != _DISCUSS_MORE.lower()]
    cleaned = cleaned[:4]
    cleaned.append(_DISCUSS_MORE)
    gui["options"] = cleaned
    payload["get_user_input"] = gui
    return json.dumps(payload)


def _prompt_path(surface: Surface) -> Path:
    return _PROMPTS_DIR / f"{surface}_brain_b.md"


def _extract_message(response: object) -> dict[str, Any]:
    choices = response.get("choices") if isinstance(response, dict) else getattr(response, "choices", None)
    if not choices:
        return {}
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else getattr(first, "message", None)
    if message is None:
        return {}
    if isinstance(message, dict):
        return message
    content = getattr(message, "content", "")
    tool_calls = getattr(message, "tool_calls", None)
    return {"content": content, "tool_calls": tool_calls}


def _message_content(message: dict[str, Any]) -> str:
    return str(message.get("content") or "").strip()


def _normalize_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    tool_calls = message.get("tool_calls")
    if not tool_calls:
        return []
    normalized: list[dict[str, Any]] = []
    for call in tool_calls:
        if isinstance(call, dict):
            normalized.append(call)
            continue
        function = getattr(call, "function", None)
        normalized.append(
            {
                "id": getattr(call, "id", ""),
                "type": getattr(call, "type", "function"),
                "function": {
                    "name": getattr(function, "name", "") if function is not None else "",
                    "arguments": getattr(function, "arguments", "") if function is not None else "",
                },
            }
        )
    return normalized


def _summarize(value: Any) -> str:
    try:
        rendered = json.dumps(value, default=str)
    except (TypeError, ValueError):
        rendered = str(value)
    if len(rendered) <= _RESULT_LOG_LIMIT:
        return rendered
    return rendered[:_RESULT_LOG_LIMIT] + "…"


def _observed_retrieval_chunks(tool_calls: list[ToolCallRecord]) -> list[str]:
    chunk_ids: list[str] = []
    for call in tool_calls:
        if call.name != "search_knowledge":
            continue
        if not isinstance(call.result, list):
            continue
        for hit in call.result:
            if not isinstance(hit, dict):
                continue
            chunk_id = hit.get("chunk_id")
            if chunk_id:
                chunk_ids.append(str(chunk_id))
    return chunk_ids


async def run_brain_b_with_tools(
    *,
    surface: Surface,
    system_context: list[str],
    transcript_tail: list[dict[str, Any]],
    registry: ToolRegistry,
    router,
    max_tool_calls: int = 4,
    max_parse_retries: int = 1,
) -> BrainBLoopResult:
    """Single tool-calling loop shared by Designer and Interviewer Brain B.

    The loop alternates between completion calls and tool dispatches until the
    model emits a terminal message (no ``tool_calls``). The terminal message
    is parsed as ``BrainBIntent``; parse failures trigger up to
    ``max_parse_retries`` recovery iterations before the loop raises.
    ``max_tool_calls`` bounds total tool invocations per turn so latency stays
    predictable. ``retrieval_used`` and ``retrieval_chunks`` on the returned
    intent are overridden from observed ``search_knowledge`` calls so the
    audit trail reflects reality, not model self-report.
    """
    system_prompt = _prompt_path(surface).read_text(encoding="utf-8").strip()
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for extra in system_context:
        if extra:
            messages.append({"role": "system", "content": extra})
    messages.extend(transcript_tail)

    tools_schema = registry.openai_schema() if not registry.is_empty() else None
    tool_calls_made: list[ToolCallRecord] = []
    parse_retries = 0
    raw_output = ""
    last_exc: Exception | None = None

    max_iterations = max_tool_calls + max_parse_retries + 1
    for iteration in range(max_iterations):
        completion_kwargs: dict[str, Any] = {
            "model": "mira-scientist",
            "messages": messages,
            "response_format": _brain_b_response_format(),
            "stream": False,
            "metadata": {"surface": surface, "brain": "B", "iteration": iteration},
        }
        if tools_schema:
            completion_kwargs["tools"] = tools_schema
            completion_kwargs["tool_choice"] = "auto"

        response = await router.acompletion(**completion_kwargs)
        message = _extract_message(response)
        tool_calls = _normalize_tool_calls(message)

        if tool_calls:
            if len(tool_calls_made) + len(tool_calls) > max_tool_calls:
                raise BrainBToolBudgetExceeded(
                    f"Brain B exceeded tool-call budget of {max_tool_calls}",
                    raw_output=_message_content(message),
                    surface=surface,
                )
            messages.append(
                {
                    "role": "assistant",
                    "content": message.get("content") or "",
                    "tool_calls": tool_calls,
                }
            )
            for call in tool_calls:
                function = call.get("function") or {}
                name = str(function.get("name") or "")
                arguments_raw = function.get("arguments") or "{}"
                tool_call_id = str(call.get("id") or "")
                try:
                    result = await registry.dispatch(name, arguments_raw)
                    result_json = json.dumps(result, default=str)
                except ToolDispatchError as exc:
                    result = {"error": str(exc), "tool": exc.tool}
                    result_json = json.dumps(result)
                    logger.warning(
                        "brain_b tool dispatch error surface=%s tool=%s err=%s",
                        surface,
                        exc.tool,
                        exc,
                    )
                try:
                    parsed_args = (
                        json.loads(arguments_raw)
                        if isinstance(arguments_raw, str) and arguments_raw.strip()
                        else {}
                    )
                    if not isinstance(parsed_args, dict):
                        parsed_args = {"raw": arguments_raw}
                except json.JSONDecodeError:
                    parsed_args = {"raw": arguments_raw}
                tool_calls_made.append(
                    ToolCallRecord(
                        name=name,
                        arguments=parsed_args,
                        result=result,
                        result_summary=_summarize(result),
                    )
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": name,
                        "content": result_json,
                    }
                )
            continue

        raw_output = _message_content(message)
        normalized = _normalize_discuss_more(raw_output)
        try:
            intent = BrainBIntent.model_validate_json(normalized)
        except (ValidationError, ValueError) as exc:
            last_exc = exc
            if parse_retries >= max_parse_retries:
                break
            parse_retries += 1
            messages.append({"role": "assistant", "content": raw_output})
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Your last response failed BrainBIntent schema validation: "
                        f"{exc}. Respond with a single valid BrainBIntent JSON object only."
                    ),
                }
            )
            continue

        observed_chunks = _observed_retrieval_chunks(tool_calls_made)
        retrieval_used = bool(observed_chunks) or any(
            call.name == "search_knowledge" for call in tool_calls_made
        )
        intent = intent.model_copy(
            update={
                "retrieval_used": retrieval_used,
                "retrieval_chunks": observed_chunks or list(intent.retrieval_chunks),
            }
        )
        return BrainBLoopResult(intent=intent, tool_calls=tool_calls_made, raw_output=raw_output)

    raise BrainBLoopError(
        f"Brain B failed to produce a valid intent after "
        f"{len(tool_calls_made)} tool calls and {parse_retries} parse retries: {last_exc}",
        raw_output=raw_output,
        surface=surface,
    )
