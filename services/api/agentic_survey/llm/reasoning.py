from __future__ import annotations

from typing import Any

from agentic_survey.llm.catalog import CatalogResolution


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
        extra_body = request.setdefault("extra_body", {})
        chat_template_kwargs = extra_body.setdefault("chat_template_kwargs", {})
        if mode == "off":
            chat_template_kwargs["enable_thinking"] = False
        elif mode == "on":
            chat_template_kwargs["enable_thinking"] = True
        elif mode == "budget":
            chat_template_kwargs["enable_thinking"] = True
            if budget is not None:
                current = request.get("max_tokens")
                if not isinstance(current, int) or current <= 0 or current > budget:
                    request["max_tokens"] = budget
        return request

    if kwarg == "reasoning_effort":
        if mode == "off":
            request["reasoning_effort"] = "minimal"
        elif mode == "on":
            request["reasoning_effort"] = "high"
        elif mode == "budget":
            request["reasoning_effort"] = "medium"
            if budget is not None:
                current = request.get("max_tokens")
                if not isinstance(current, int) or current <= 0 or current > budget:
                    request["max_tokens"] = budget
        return request

    return request
