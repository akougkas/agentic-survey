from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, AsyncIterator

from agentic_survey.domain.intent import BrainBIntent

__all__ = ["stream_brain_a"]

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


async def stream_brain_a(
    *,
    role: str,
    prompt_md_path: str,
    transcript_tail: list[dict[str, Any]],
    brain_b_intent: BrainBIntent,
    persona: str,
    router,
    participant_context: dict[str, str] | None = None,
) -> AsyncIterator[str]:
    """Stream Brain A's conversational reply token-by-token.

    ``role`` is the LiteLLM model-list alias (e.g., ``"mira-chatter"``).
    ``prompt_md_path`` resolves under ``agents/prompts/`` when relative.
    ``brain_b_intent`` is injected as a system message; the UI renders
    ``get_user_input.options`` separately as chip buttons, so Brain A must
    not echo them inside the prose body. ``participant_context`` carries
    pre-interview micro-form answers; when present, a calibration system
    message is inserted before persona hints so tone and vocabulary align
    from the first token.
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

    stream = await router.acompletion(
        model=role,
        messages=messages,
        stream=True,
        metadata={"surface": "designer", "brain": "A"},
    )
    async for chunk in stream:
        text = _extract_chunk_text(chunk)
        if text:
            yield text
