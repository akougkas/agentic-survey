from __future__ import annotations

import json
from typing import Any
from typing import Iterable

from agentic_survey.llm.catalog import CatalogResolution

DEFAULT_VISIBLE_REPLY_MAX_TOKENS = 512
DEFAULT_REPAIR_COMPLETION_TOKENS = 1024
DEFAULT_REASONING_BUDGET_TOKENS = 8192
DEFAULT_REASONING_FINAL_RESPONSE_TOKENS = 4096

# Backstop constants for docs/tests and callers that need a module-level value.
# Runtime request builders use the functions below so local SURVEY_* settings win.
VISIBLE_REPLY_MAX_TOKENS = DEFAULT_VISIBLE_REPLY_MAX_TOKENS
REPAIR_COMPLETION_TOKENS = DEFAULT_REPAIR_COMPLETION_TOKENS
REASONING_BUDGET_TOKENS = DEFAULT_REASONING_BUDGET_TOKENS
REASONING_FINAL_RESPONSE_TOKENS = DEFAULT_REASONING_FINAL_RESPONSE_TOKENS
MIN_REASONING_COMPLETION_TOKENS = (
    DEFAULT_REASONING_BUDGET_TOKENS + DEFAULT_REASONING_FINAL_RESPONSE_TOKENS
)


def visible_reply_max_tokens() -> int:
    from agentic_survey.config import get_settings

    return get_settings().llm_visible_reply_max_tokens


def repair_completion_tokens() -> int:
    from agentic_survey.config import get_settings

    return get_settings().llm_repair_completion_tokens


def reasoning_budget_tokens() -> int:
    from agentic_survey.config import get_settings

    return get_settings().llm_reasoning_budget_tokens


def reasoning_final_response_tokens() -> int:
    from agentic_survey.config import get_settings

    return get_settings().llm_reasoning_final_response_tokens


def preplan_reasoning_budget_tokens() -> int:
    from agentic_survey.config import get_settings

    return get_settings().llm_preplan_reasoning_budget_tokens


def reasoning_completion_tokens(reasoning_budget: int | None = None) -> int:
    budget = (
        reasoning_budget
        if reasoning_budget is not None and reasoning_budget > 0
        else reasoning_budget_tokens()
    )
    return budget + reasoning_final_response_tokens()


def extract_json_object_text(
    raw: str,
    *,
    required_keys: Iterable[str] = (),
) -> str:
    """Return the last JSON object embedded in ``raw``.

    Reasoning-capable local models can put the final structured answer in
    ``reasoning_content`` and leave visible ``content`` empty. Some emit the
    JSON object directly, while others wrap it in prose or scratchpad text.
    Use Python's JSON decoder to recover complete objects without treating
    arbitrary reasoning text as user-visible output.
    """
    text = raw.strip()
    if not text:
        return ""
    required = set(required_keys)
    decoder = json.JSONDecoder()
    candidates: list[str] = []
    index = 0
    while index < len(text):
        start = text.find("{", index)
        if start < 0:
            break
        try:
            value, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(value, dict) and (not required or required.intersection(value)):
            candidates.append(text[start : start + end])
        index = start + max(end, 1)
    return candidates[-1] if candidates else ""


def _ensure_min_max_tokens(request: dict[str, Any], minimum: int) -> None:
    current = request.get("max_tokens")
    if not isinstance(current, int) or current <= 0 or current < minimum:
        request["max_tokens"] = minimum


def set_lmstudio_thinking(
    request: dict[str, Any],
    *,
    enabled: bool,
    min_tokens: int | None = None,
) -> dict[str, Any]:
    """Set LM Studio chat-template thinking without disturbing other body args."""
    extra_body = request.setdefault("extra_body", {})
    chat_template_kwargs = extra_body.setdefault("chat_template_kwargs", {})
    chat_template_kwargs["enable_thinking"] = enabled
    if min_tokens is not None:
        _ensure_min_max_tokens(request, min_tokens)
    if not enabled:
        request.pop("reasoning_effort", None)
    return request


class TrailingAssistantRoleError(RuntimeError):
    """Raised when a thinking-enabled request carries a malformed trailing role.

    Gemma's llama-server chat template treats a trailing ``assistant`` message
    as a partial-response prefill the model should continue from. When
    ``chat_template_kwargs.enable_thinking=true`` is also set, the server
    rejects the request with HTTP 400 ``Assistant response prefill is
    incompatible with enable_thinking``. The sanitizer below normalizes a
    trailing assistant message into a follow-up ``user`` turn so the chat
    template treats it as completed assistant context. Any role outside the
    OpenAI-spec set ``{system, user, assistant, tool}`` raises this error so
    the caller surfaces a clear failure instead of letting llama-server emit
    a cryptic 400.
    """


_VALID_OPENAI_ROLES: frozenset[str] = frozenset(
    {"system", "user", "assistant", "tool"}
)


def sanitize_thinking_messages(
    messages: list[dict[str, Any]],
    *,
    follow_up: str = "Continue.",
) -> list[dict[str, Any]]:
    """Ensure ``messages[-1]`` is safe for a thinking-enabled llama-server call.

    Gemma's llama-server chat template reads a trailing ``assistant`` entry as
    a response prefill it should continue from. When the same request also
    carries ``chat_template_kwargs.enable_thinking=true``, the server returns
    HTTP 400 ``Assistant response prefill is incompatible with enable_thinking``.
    The same call shape works on the dynamo Gemma backend that ships every
    Brain B / Validator / Analyst role, so the sanitizer fires before each
    thinking-enabled completion call:

    - Last message is ``assistant`` with a non-empty ``content``: append a
      synthetic ``{"role": "user", "content": follow_up}`` so the chat template
      sees a completed assistant turn followed by a fresh user prompt.
    - Last message is ``assistant`` with empty ``content`` and no ``tool_calls``:
      drop it. The empty entry carries no signal and would still trigger the
      prefill path. If dropping leaves an empty message list the sanitizer
      raises so the caller surfaces a clear failure.
    - Last message is ``assistant`` with ``tool_calls`` but no ``content``:
      this is a malformed payload pre-tool-dispatch (an assistant tool-call
      message must be followed by ``tool`` rows). Raise ``TrailingAssistantRoleError``.
    - Last message is ``tool``, ``user``, or ``system``: no-op.
    - Last message has any other role: raise ``TrailingAssistantRoleError``.

    The function returns a NEW list. The caller's ``messages`` reference is
    untouched so the loop's tool-call accounting (which still appends to the
    original list across iterations) keeps working.
    """
    if not messages:
        raise TrailingAssistantRoleError(
            "thinking-enabled request must carry at least one message"
        )
    last = messages[-1]
    role = str(last.get("role") or "").strip()
    if role not in _VALID_OPENAI_ROLES:
        raise TrailingAssistantRoleError(
            f"thinking-enabled request has invalid trailing role {role!r}; "
            f"expected one of {sorted(_VALID_OPENAI_ROLES)}"
        )
    if role != "assistant":
        return list(messages)
    content = str(last.get("content") or "").strip()
    tool_calls = last.get("tool_calls")
    if not content:
        if tool_calls:
            raise TrailingAssistantRoleError(
                "thinking-enabled request ends on an assistant tool_calls message; "
                "tool dispatch must append role=tool rows before the next call"
            )
        if len(messages) <= 1:
            raise TrailingAssistantRoleError(
                "thinking-enabled request would be emptied by stripping the "
                "trailing assistant message"
            )
        return list(messages[:-1])
    return [*messages, {"role": "user", "content": follow_up}]


def _mode_to_reasoning_effort(mode: str) -> str:
    """Map our internal reasoning_mode to OpenAI / OpenRouter reasoning_effort."""
    if mode == "on":
        return "high"
    if mode == "budget":
        return "medium"
    return "minimal"


def apply_reasoning_settings(
    resolution: CatalogResolution,
    request: dict[str, Any],
) -> dict[str, Any]:
    kwarg = resolution.reasoning_kwarg
    mode = resolution.reasoning_mode
    budget = resolution.reasoning_budget_tokens

    if kwarg == "none":
        return request

    if kwarg == "enable_thinking":
        if mode == "off":
            set_lmstudio_thinking(
                request,
                enabled=False,
                min_tokens=visible_reply_max_tokens(),
            )
        elif mode == "on":
            set_lmstudio_thinking(
                request,
                enabled=True,
                min_tokens=reasoning_completion_tokens(),
            )
        elif mode == "budget":
            set_lmstudio_thinking(
                request,
                enabled=True,
                min_tokens=reasoning_completion_tokens(budget),
            )
        # Mirror the mode onto reasoning_effort so the same prepared request
        # works when the same model_name rotates to OpenRouter (which speaks
        # the OpenAI-style reasoning_effort param). LM Studio ignores it; the
        # `extra_body.chat_template_kwargs.enable_thinking` is ignored by
        # OpenRouter. One request shape fits both backends.
        request["reasoning_effort"] = _mode_to_reasoning_effort(mode)
        return request

    if kwarg == "reasoning_effort":
        if mode == "off":
            request["reasoning_effort"] = "minimal"
            _ensure_min_max_tokens(request, visible_reply_max_tokens())
        elif mode == "on":
            request["reasoning_effort"] = "high"
            _ensure_min_max_tokens(request, reasoning_completion_tokens())
        elif mode == "budget":
            request["reasoning_effort"] = "medium"
            _ensure_min_max_tokens(
                request,
                reasoning_completion_tokens(budget),
            )
        return request

    return request
