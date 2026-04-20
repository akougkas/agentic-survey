from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from pydantic import ValidationError

from agentic_survey.domain.intent import BrainBIntent
from agentic_survey.domain.outline import OutlineArtifact
from agentic_survey.engine.session_policy import SessionSignals

__all__ = [
    "InterviewerBrainBError",
    "run_brain_b_interviewer",
    "SearchKnowledge",
]

_PROMPTS_DIR = Path(__file__).with_name("prompts")
_DEFAULT_PROMPT_FILE = "interviewer_brain_b.md"

SearchKnowledge = Callable[[str, int], Awaitable[list[dict[str, Any]]]]


class InterviewerBrainBError(RuntimeError):
    """Raised when Interviewer Brain B does not return a valid BrainBIntent after one retry."""

    def __init__(self, message: str, *, raw_output: str = "") -> None:
        super().__init__(message)
        self.raw_output = raw_output


def _brain_b_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "brain_b_intent",
            "schema": BrainBIntent.model_json_schema(),
        },
    }


_DISCUSS_MORE = "Discuss this more."


def _normalize_discuss_more(raw: str) -> str:
    """Ensure ``get_user_input.options`` ends with 'Discuss this more.'.

    Mirror of the Designer's normalizer — local models do not always honor
    the contract verbatim, and cosmetic prompt lapses should not blow up
    the whole turn. Falls through on unparseable output so existing
    ValidationError diagnostics remain intact.
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
    cleaned: list[str] = [str(opt).strip() for opt in options if str(opt).strip()]
    cleaned = [opt for opt in cleaned if opt.lower() != _DISCUSS_MORE.lower()]
    cleaned = cleaned[:4]
    cleaned.append(_DISCUSS_MORE)
    gui["options"] = cleaned
    payload["get_user_input"] = gui
    return json.dumps(payload)


def _extract_message_content(response: object) -> str:
    choices = response.get("choices") if isinstance(response, dict) else getattr(response, "choices", None)
    if not choices:
        return ""
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else getattr(first, "message", None)
    if message is None:
        return ""
    if isinstance(message, dict):
        content = message.get("content")
    else:
        content = getattr(message, "content", None)
    return str(content or "").strip()


async def run_brain_b_interviewer(
    *,
    outline: OutlineArtifact,
    transcript_tail: list[dict[str, Any]],
    session_signals: SessionSignals,
    router,
    search_knowledge: SearchKnowledge,
) -> BrainBIntent:
    """Invoke Interviewer Brain B and return a validated ``BrainBIntent``.

    The returned intent authorizes close via ``should_close``. The session
    policy helpers never make that call on their own; they only surface
    advisory signals here. ``search_knowledge`` is a no-op in Phase A and
    any retrieval activity lives on ``retrieval_used`` / ``retrieval_chunks``
    fields of the returned intent (populated by B2-min and later).
    """
    _ = search_knowledge  # reserved for Phase B tool-dispatch

    system_prompt = (_PROMPTS_DIR / _DEFAULT_PROMPT_FILE).read_text(encoding="utf-8").strip()
    outline_blob = outline.model_dump_json(indent=2)
    signals_blob = session_signals.model_dump_json(indent=2)

    base_messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": f"Current outline:\n{outline_blob}"},
        {"role": "system", "content": f"Session signals (advisory, close is still yours):\n{signals_blob}"},
    ]
    base_messages.extend(transcript_tail)

    response_format = _brain_b_response_format()
    raw_output = ""
    last_exc: Exception | None = None

    for attempt in range(2):
        response = await router.acompletion(
            model="mira-scientist",
            messages=base_messages,
            response_format=response_format,
            stream=False,
            metadata={"surface": "interviewer", "brain": "B", "attempt": attempt},
        )
        raw_output = _extract_message_content(response)
        raw_output = _normalize_discuss_more(raw_output)
        try:
            intent = BrainBIntent.model_validate_json(raw_output)
        except (ValidationError, ValueError) as exc:
            last_exc = exc
            continue
        return intent

    raise InterviewerBrainBError(
        f"Interviewer Brain B output failed to parse after one retry: {last_exc}",
        raw_output=raw_output,
    )
