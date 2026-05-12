from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, AsyncIterator

from agentic_survey.domain.intent import BrainBIntent
from agentic_survey.domain.outline import OutlineArtifact
from agentic_survey.domain.tools import GetUserInputOptions
from agentic_survey.llm.callbacks import failure_callback, success_callback
from agentic_survey.llm.catalog import CatalogResolution
from agentic_survey.llm.reasoning import (
    apply_reasoning_settings,
    set_lmstudio_thinking,
    visible_reply_max_tokens,
)

__all__ = ["build_scaffold_intent", "stream_brain_a"]

_DISCUSS_CHIP = "Discuss this more."
_SCAFFOLD_MAX_CHIPS = 3

_PROMPTS_DIR = Path(__file__).with_name("prompts")
_PERSONA_PATH = _PROMPTS_DIR / "mira_persona.md"


@lru_cache(maxsize=1)
def _persona_preamble() -> str:
    return _PERSONA_PATH.read_text(encoding="utf-8").strip()


def _load_prompt(prompt_md_path: str) -> str:
    candidate = Path(prompt_md_path)
    if not candidate.is_absolute():
        candidate = _PROMPTS_DIR / prompt_md_path
    return candidate.read_text(encoding="utf-8").strip()


def _load_chatter_prompt(prompt_md_path: str) -> str:
    return f"{_persona_preamble()}\n\n{_load_prompt(prompt_md_path)}"


def _format_participant_context(context: dict[str, str] | None) -> str:
    if not context:
        return ""
    lines: list[str] = []
    for key, raw_value in context.items():
        if not isinstance(raw_value, str):
            continue
        value = raw_value.strip()
        if not value:
            continue
        lines.append(f'- {key}: "{value}"')
    if not lines:
        return ""
    return (
        "The respondent answered the pre-interview micro-form as follows:\n"
        + "\n".join(lines)
        + "\n\nCalibrate your register from turn one. Mirror their vocabulary. "
        "Do not flatten to corporate tone."
    )


def _extract_chunk_text(chunk: object) -> str:
    choices = chunk.get("choices") if isinstance(chunk, dict) else getattr(chunk, "choices", None)
    if not choices:
        return ""
    first = choices[0]
    delta = first.get("delta") if isinstance(first, dict) else getattr(first, "delta", None)
    if delta is None:
        message = first.get("message") if isinstance(first, dict) else getattr(first, "message", None)
        if message is None:
            return ""
        content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
        return str(content or "")
    if isinstance(delta, dict):
        return str(delta.get("content") or "")
    return str(getattr(delta, "content", "") or "")


def build_scaffold_intent(
    *,
    outline: OutlineArtifact,
    participant_context: dict[str, str] | None,
    transcript_tail: list[dict[str, Any]] | None,
) -> BrainBIntent:
    """Minimal Brain-B stand-in used when no pre-computed plan exists.

    Brain A renders this the same way it would render a real plan, so
    the participant never sees a stall while the background planner
    catches up. The scaffold is deliberately shallow:

    - ``active_axis`` is the first outline axis (we have no coverage
      state yet).
    - ``get_user_input.options`` rotates the first two outline probes as
      short chip labels, ending with the canonical ``"Discuss this
      more."`` option; ``allow_free_text`` stays on.
    - ``retrieval_used`` is ``False`` and ``retrieval_chunks`` is empty —
      scaffold mode never invokes retrieval.
    """
    del transcript_tail, participant_context  # reserved for later register mirroring.

    axes = [axis.strip() for axis in (outline.axes or []) if axis and axis.strip()]
    active_axis = axes[0] if axes else ""
    axis_hint = active_axis or "what you were doing"
    question_intent = f"Open with one concrete recent example from {axis_hint}."

    probes = [probe.strip() for probe in (outline.probes or []) if probe and probe.strip()]
    chip_options: list[str] = []
    for probe in probes:
        if len(chip_options) >= _SCAFFOLD_MAX_CHIPS - 1:
            break
        label = _shorten_chip(probe)
        if label and label not in chip_options:
            chip_options.append(label)
    while len(chip_options) < _SCAFFOLD_MAX_CHIPS - 1:
        chip_options.append("Share a recent moment")
    chip_options.append(_DISCUSS_CHIP)

    default_question = (
        "Can you walk me through a recent moment this showed up at work?"
    )
    question = probes[0] if probes else default_question

    return BrainBIntent(
        active_axis=active_axis,
        axes_coverage=[],
        question_intent=question_intent,
        get_user_input=GetUserInputOptions(
            question=question,
            options=chip_options,
            allow_free_text=True,
        ),
        outline_patch=None,
        ready_for_review=False,
        should_close=False,
        closing=False,
        retrieval_used=False,
        retrieval_chunks=[],
    )


def _shorten_chip(text: str, *, max_words: int = 6) -> str:
    cleaned = text.strip().rstrip("?.!").strip()
    if not cleaned:
        return ""
    tokens = cleaned.split()
    if len(tokens) <= max_words:
        return cleaned
    return " ".join(tokens[:max_words])


async def stream_brain_a(
    *,
    role: str,
    prompt_md_path: str,
    transcript_tail: list[dict[str, Any]],
    brain_b_intent: BrainBIntent,
    persona: str,
    router,
    participant_context: dict[str, str] | None = None,
    catalog_resolution: CatalogResolution | None = None,
    surface: str = "designer",
    campaign_id: str | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
) -> AsyncIterator[str]:
    """Stream Brain A's conversational reply token-by-token.

    ``role`` is the LiteLLM model-list alias (e.g., ``"mira-chatter"``).
    ``prompt_md_path`` resolves under ``agents/prompts/`` when relative.
    ``brain_b_intent`` is injected as a system message; the UI renders
    ``get_user_input.options`` separately as chip buttons, so Brain A must
    not echo them inside the prose body. ``participant_context`` carries
    pre-interview micro-form answers; when present, a calibration system
    message is inserted before persona hints so tone and vocabulary align
    from the first token. ``catalog_resolution`` carries the chatter route
    resolved by the caller so ``apply_reasoning_settings`` runs at request
    build time. When omitted the call still produces a chatter-shaped
    request via ``set_lmstudio_thinking(enabled=False)``; production wires
    the resolution from ``LLMClient`` so flipping endpoints (mini, dynamo,
    OpenRouter) is an env-var change rather than a source edit.
    """
    system_prompt = _load_chatter_prompt(prompt_md_path)
    persona_blob = persona.strip()
    intent_blob = brain_b_intent.model_dump_json(indent=2)

    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    context_block = _format_participant_context(participant_context)
    if context_block:
        messages.append({"role": "system", "content": context_block})
    if persona_blob:
        messages.append({"role": "system", "content": f"Persona hints:\n{persona_blob}"})
    messages.extend(transcript_tail)
    messages.append(
        {
            "role": "system",
            "content": (
                "Brain B intent for this turn. Render the next probe as short "
                "natural prose. Do NOT print the chip options inside your reply "
                "text; the UI displays them separately.\n"
                f"{intent_blob}"
            ),
        }
    )

    request: dict[str, Any] = {
        "model": role,
        "messages": messages,
        "stream": True,
        "max_tokens": visible_reply_max_tokens(),
        "metadata": {
            "surface": surface,
            "brain": "A",
            "campaign_id": campaign_id,
            "session_id": session_id,
            "turn_id": turn_id,
        },
    }
    if catalog_resolution is not None:
        request["metadata"].update(
            {
                "catalog_id": catalog_resolution.catalog_id,
                "catalog_role": catalog_resolution.role,
                "router_alias": role,
                "route_source": catalog_resolution.source,
                "endpoint_name": catalog_resolution.endpoint,
                "endpoint_model": catalog_resolution.model_id,
                "reasoning_mode": catalog_resolution.reasoning_mode,
                "reasoning_kwarg": catalog_resolution.reasoning_kwarg,
                "reasoning_budget_tokens": catalog_resolution.reasoning_budget_tokens,
            }
        )
        apply_reasoning_settings(catalog_resolution, request)
        if catalog_resolution.temperature is not None:
            request["temperature"] = catalog_resolution.temperature
    else:
        set_lmstudio_thinking(request, enabled=False)
    start_time = datetime.now(tz=UTC)
    try:
        stream = await router.acompletion(**request)
    except Exception as exc:
        failure_callback(request, exc, start_time, datetime.now(tz=UTC))
        raise
    try:
        async for chunk in stream:
            text = _extract_chunk_text(chunk)
            if text:
                yield text
    except Exception as exc:
        failure_callback(request, exc, start_time, datetime.now(tz=UTC))
        raise
    success_callback(request, {}, start_time, datetime.now(tz=UTC))
