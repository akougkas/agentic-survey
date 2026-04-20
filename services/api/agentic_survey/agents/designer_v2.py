from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentic_survey.agents.brain_a import stream_brain_a
from agentic_survey.agents.brain_b_designer import (
    DesignerBrainBError,
    run_brain_b_designer,
)
from agentic_survey.agents.readiness import unmet_minimums
from agentic_survey.domain.intent import BrainBIntent, OutlinePatch
from agentic_survey.domain.outline import OutlineArtifactV2, from_v1, to_v1
from agentic_survey.llm.router import LiteLLMRouter
from agentic_survey.repository import Campaign, DesignerSession, OutlineArtifact

__all__ = [
    "DESIGNER_BRAIN_A_PROMPT",
    "DesignerBrainBError",
    "DesignerTurnResult",
    "apply_outline_patch",
    "build_transcript_tail",
    "compose_persona",
    "is_ready_for_review",
    "opening_message",
    "run_designer_turn",
]

DESIGNER_BRAIN_A_PROMPT = "designer_brain_a.md"


@dataclass(slots=True)
class DesignerTurnResult:
    reply_text: str
    brain_b_intent: BrainBIntent
    updated_outline: OutlineArtifact
    updated_outline_v2: OutlineArtifactV2
    ready: bool
    unmet: list[str]


def opening_message(campaign: Campaign) -> str:
    return (
        f"I'm Mira. Let's turn {campaign.title} into a study the interviews can actually settle. "
        "Start with the question you need answered, even if the wording is still rough."
    )


def is_ready_for_review(
    outline: OutlineArtifact | OutlineArtifactV2,
    brain_b_ready: bool,
) -> tuple[bool, list[str]]:
    """Hard-floor + Brain B self-report composite readiness gate.

    Lifts legacy v1 outlines via ``from_v1`` so the floor always runs
    against the v2 shape. Returns ``(ready, unmet)`` where ``ready`` is
    True only when the unmet list is empty *and* Brain B signalled ready.
    """
    outline_v2 = outline if isinstance(outline, OutlineArtifactV2) else from_v1(outline)
    unmet = unmet_minimums(outline_v2)
    ready = len(unmet) == 0 and brain_b_ready
    return ready, unmet


def compose_persona(persona_hints: dict[str, str]) -> str:
    """Flatten persona_hints into a short system-message blob Brain A can cite."""
    if not persona_hints:
        return ""
    ordered_keys = ("name", "role", "tone", "behavior")
    lines: list[str] = []
    for key in ordered_keys:
        value = persona_hints.get(key)
        if value:
            lines.append(f"{key}: {value}")
    for key, value in persona_hints.items():
        if key in ordered_keys or not value:
            continue
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


def build_transcript_tail(session: DesignerSession | None, *, tail: int = 6) -> list[dict[str, Any]]:
    """Render the last ``tail`` Designer turns as OpenAI-style chat messages."""
    if session is None:
        return []
    messages: list[dict[str, Any]] = []
    for turn in session.turns[-tail:]:
        role = "assistant" if turn.role == "designer" else "user"
        messages.append({"role": role, "content": turn.content})
    return messages


def apply_outline_patch(outline_v2: OutlineArtifactV2, patch: OutlinePatch) -> OutlineArtifactV2:
    """Apply a Brain B outline patch section-by-section against a v2 outline.

    Unknown sections are skipped rather than raised; Brain B prompts are
    still being tuned (M10) and we do not want a single bad field name to
    drop the whole turn. replace sets the value, append extends lists,
    remove filters list items by equality.
    """
    working = outline_v2.model_copy(deep=True)
    for section in patch.sections:
        if not hasattr(working, section.section):
            continue
        current = getattr(working, section.section)
        if section.op == "replace":
            setattr(working, section.section, section.value)
        elif section.op == "append":
            if isinstance(current, list):
                new_list = list(current)
                new_list.append(section.value)
                setattr(working, section.section, new_list)
        elif section.op == "remove":
            if isinstance(current, list):
                setattr(
                    working,
                    section.section,
                    [item for item in current if item != section.value],
                )
    return working


async def _noop_search_knowledge(query: str, k: int) -> list[dict[str, Any]]:
    return []


async def run_designer_turn(
    *,
    campaign: Campaign,
    session: DesignerSession | None,
    router: LiteLLMRouter,
) -> DesignerTurnResult:
    """Execute one Designer turn end-to-end.

    Flow: lift the campaign's v1 outline to v2, invoke Brain B against the
    current transcript tail, apply any returned ``outline_patch`` to a
    working v2 copy, stream Brain A's reply tokens (assembled into a final
    string), compose readiness from the hard floor plus Brain B's
    self-report, and hand back the updated outline in both shapes so the
    caller can persist via the v1 repository path.
    """
    outline_v2 = from_v1(campaign.outline)
    transcript_tail = build_transcript_tail(session)
    persona = compose_persona(campaign.outline.persona_hints)

    captured_patch: dict[str, Any] = {}

    def _propose(patch: dict[str, Any]) -> None:
        captured_patch.update(patch)

    intent = await run_brain_b_designer(
        outline=outline_v2,
        transcript_tail=transcript_tail,
        router=router,
        search_knowledge=_noop_search_knowledge,
        get_outline_state=lambda: outline_v2,
        list_grounding_sources=lambda: [],
        propose_outline_patch=_propose,
    )

    updated_v2 = (
        apply_outline_patch(outline_v2, intent.outline_patch)
        if intent.outline_patch is not None
        else outline_v2
    )

    chunks: list[str] = []
    async for token in stream_brain_a(
        role="mira-chatter",
        prompt_md_path=DESIGNER_BRAIN_A_PROMPT,
        transcript_tail=transcript_tail,
        brain_b_intent=intent,
        persona=persona,
        router=router,
    ):
        chunks.append(token)
    reply_text = "".join(chunks).strip()

    updated_v1 = to_v1(updated_v2)
    ready, unmet = is_ready_for_review(updated_v2, intent.ready_for_review)
    return DesignerTurnResult(
        reply_text=reply_text,
        brain_b_intent=intent,
        updated_outline=updated_v1,
        updated_outline_v2=updated_v2,
        ready=ready,
        unmet=unmet,
    )
