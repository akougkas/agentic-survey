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
) -> AsyncIterator[str]:
    """Stream Brain A's conversational reply token-by-token.

    ``role`` is the LiteLLM model-list alias (e.g., ``"mira-chatter"``).
    ``prompt_md_path`` resolves under ``agents/prompts/`` when relative.
    ``brain_b_intent`` is injected as a system message; Brain A is expected
    to render ``brain_b_intent.get_user_input.options`` verbatim at the end
    of its prose per the designer-interview contract (chips-last). The
    caller assembles yielded tokens; if the assembled reply lacks the chip
    rendering, the orchestrator raises rather than fabricating it.
    """
    system_prompt = _load_chatter_prompt(prompt_md_path)
    persona_blob = persona.strip()
    intent_blob = brain_b_intent.model_dump_json(indent=2)

    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if persona_blob:
        messages.append({"role": "system", "content": f"Persona hints:\n{persona_blob}"})
    messages.extend(transcript_tail)
    messages.append(
        {
            "role": "system",
            "content": (
                "Brain B intent for this turn. Do not repeat the JSON; render "
                "get_user_input.options verbatim as chips at the end of your prose.\n"
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
