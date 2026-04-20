from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from pydantic import ValidationError

from agentic_survey.domain.intent import BrainBIntent
from agentic_survey.domain.outline import OutlineArtifactV2

__all__ = [
    "DesignerBrainBError",
    "GetOutlineState",
    "ListGroundingSources",
    "ProposeOutlinePatch",
    "SearchKnowledge",
    "run_brain_b_designer",
]

_PROMPTS_DIR = Path(__file__).with_name("prompts")
_DEFAULT_PROMPT_FILE = "designer_brain_b.md"

SearchKnowledge = Callable[[str, int], Awaitable[list[dict[str, Any]]]]
GetOutlineState = Callable[[], OutlineArtifactV2]
ListGroundingSources = Callable[[], list[dict[str, Any]]]
ProposeOutlinePatch = Callable[[dict[str, Any]], None]


class DesignerBrainBError(RuntimeError):
    """Raised when Brain B does not return a valid BrainBIntent after one retry."""

    def __init__(self, message: str, *, raw_output: str = "") -> None:
        super().__init__(message)
        self.raw_output = raw_output


def _brain_b_response_format() -> dict[str, Any]:
    schema = BrainBIntent.model_json_schema()
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "brain_b_intent",
            "schema": schema,
        },
    }


_DISCUSS_MORE = "Discuss this more."


def _normalize_discuss_more(raw: str) -> str:
    """Ensure ``get_user_input.options`` ends with 'Discuss this more.'.

    Local models do not always honor this contract verbatim. Rather than fail
    the whole turn on a cosmetic prompt lapse, we normalize the options list:
    dedupe a trailing match, truncate to 4, and append the canonical string.
    If parsing fails we pass the raw text through unchanged so the caller's
    ValidationError path keeps its existing diagnostics.
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


async def run_brain_b_designer(
    *,
    outline: OutlineArtifactV2,
    transcript_tail: list[dict[str, Any]],
    router,
    search_knowledge: SearchKnowledge,
    get_outline_state: GetOutlineState,
    list_grounding_sources: ListGroundingSources,
    propose_outline_patch: ProposeOutlinePatch,
) -> BrainBIntent:
    """Invoke Designer Brain B and return a validated ``BrainBIntent``.

    The callables mirror Brain B's logical tool surface. In Phase A the
    orchestrator passes stubs (``search_knowledge`` returns ``[]``,
    ``propose_outline_patch`` is captured but the patch lives inside the
    returned intent). One retry is issued when the first response fails to
    parse; a second failure raises ``DesignerBrainBError`` carrying the
    malformed output so callers can log it.
    """
    _ = get_outline_state  # reserved for Phase B tool-dispatch; outline is already serialized below
    _ = search_knowledge   # reserved for Phase B tool-dispatch

    system_prompt = (_PROMPTS_DIR / _DEFAULT_PROMPT_FILE).read_text(encoding="utf-8").strip()
    outline_blob = outline.model_dump_json(indent=2)
    grounding_blob = json.dumps(list_grounding_sources(), indent=2)

    base_messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": f"Current outline (v2):\n{outline_blob}"},
        {"role": "system", "content": f"Approved grounding sources:\n{grounding_blob}"},
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
            metadata={"surface": "designer", "brain": "B", "attempt": attempt},
        )
        raw_output = _extract_message_content(response)
        normalized = _normalize_discuss_more(raw_output)
        try:
            intent = BrainBIntent.model_validate_json(normalized)
        except (ValidationError, ValueError) as exc:
            last_exc = exc
            continue

        if intent.outline_patch is not None:
            try:
                propose_outline_patch(intent.outline_patch.model_dump())
            except Exception:
                # Callbacks are advisory in Phase A; the orchestrator applies the patch authoritatively.
                pass
        return intent

    raise DesignerBrainBError(
        f"Brain B output failed to parse after one retry: {last_exc}",
        raw_output=raw_output,
    )
