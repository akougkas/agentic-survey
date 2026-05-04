from __future__ import annotations

from typing import Any

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
            set_lmstudio_thinking(request, enabled=False)
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
        return request

    if kwarg == "reasoning_effort":
        if mode == "off":
            request["reasoning_effort"] = "minimal"
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
