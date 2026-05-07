from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agentic_survey.agents.brain_a import stream_brain_a
from agentic_survey.agents.brain_b_designer import (
    DesignerBrainBError,
    run_brain_b_designer,
)
from agentic_survey.agents.readiness import unmet_minimums
from agentic_survey.domain.intent import BrainBIntent, OutlinePatch
from agentic_survey.domain.outline import OutlineArtifact
from agentic_survey.llm.client import resolve_catalog_route
from agentic_survey.llm.router import LiteLLMRouter
from agentic_survey.repository import Campaign, DesignerSession
from agentic_survey.services.graph import build_neighborhood_provider
from agentic_survey.services.retrieval import build_search_knowledge
from agentic_survey.services.web_search.suggestions import (
    SearchSuggestionsRejected,
    assert_design_time,
    queue_proposed_queries,
)

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
    ready: bool
    unmet: list[str]


def opening_message(campaign: Campaign) -> str:
    return (
        f"I'm Mira. Let's turn {campaign.title} into a study the interviews can actually settle. "
        "Start with the question you need answered, even if the wording is still rough."
    )


def is_ready_for_review(
    outline: OutlineArtifact,
    brain_b_ready: bool,
) -> tuple[bool, list[str]]:
    """Hard-floor + Brain B self-report composite readiness gate.

    Returns ``(ready, unmet)``; ``ready`` is True only when the unmet list is
    empty *and* Brain B signalled ready.
    """
    unmet = unmet_minimums(outline)
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


def apply_outline_patch(outline: OutlineArtifact, patch: OutlinePatch) -> OutlineArtifact:
    """Apply a Brain B outline patch section-by-section.

    Unknown sections are skipped rather than raised. ``replace`` sets the
    value, ``append`` extends lists, ``remove`` filters list items by
    equality.
    """
    working = outline.model_copy(deep=True)
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


async def _noop_search_knowledge(
    query: str, k: int, mode: str = "hybrid"
) -> list[dict[str, Any]]:
    return []


def _list_approved_grounding_sources(repository, campaign_id: str) -> list[dict[str, Any]]:
    """Snapshot approved knowledge sources for the Brain-B grounding tool.

    Returns a compact shape (id, title, kind, status, rationale) so Brain B
    can reason about what is already on hand without getting buried in chunk
    bodies. The search_knowledge tool remains the path to actual content.
    """
    if repository is None:
        return []
    sources = repository.list_knowledge_sources(campaign_id)
    snapshot: list[dict[str, Any]] = []
    for source in sources:
        if getattr(source, "status", "") != "approved":
            continue
        snapshot.append(
            {
                "id": getattr(source, "id", ""),
                "title": getattr(source, "title", ""),
                "kind": getattr(source, "kind", ""),
                "status": getattr(source, "status", ""),
                "rationale": getattr(source, "rationale", ""),
            }
        )
    return snapshot


async def run_designer_turn(
    *,
    campaign: Campaign,
    session: DesignerSession | None,
    router: LiteLLMRouter,
    repository=None,
) -> DesignerTurnResult:
    """Execute one Designer turn end-to-end.

    Flow: invoke Brain B against the current transcript tail, apply any
    returned ``outline_patch`` to a working copy, stream Brain A's reply,
    and compose readiness from the hard floor plus Brain B's self-report.
    """
    outline = campaign.outline
    transcript_tail = build_transcript_tail(session)
    persona = compose_persona(campaign.outline.persona_hints)

    captured_patch: dict[str, Any] = {}

    def _propose(patch: dict[str, Any]) -> None:
        captured_patch.update(patch)

    search_fn = (
        build_search_knowledge(
            repository=repository,
            campaign_id=campaign.id,
            surface="designer",
            router=router,
        )
        if repository is not None
        else _noop_search_knowledge
    )
    grounding_sources = _list_approved_grounding_sources(repository, campaign.id)
    propose_queries_fn: Callable[[list[str]], list[str]] | None = None
    if repository is not None:
        def _queue_queries(queries: list[str]) -> list[str]:
            # M3 invariant: design-time only. Re-fetch the campaign so a
            # turn that started in DESIGNING but raced with a LIVE
            # transition (another admin request) still rejects cleanly.
            # Using the captured ``campaign`` snapshot would read stale
            # state. Errors surface to Brain B as a tool-dispatch error
            # per ``ToolRegistry``.
            fresh = repository.get_campaign(campaign.id)
            if fresh is None:
                raise SearchSuggestionsRejected(
                    f"Campaign {campaign.id} not found"
                )
            assert_design_time(fresh.state)
            return queue_proposed_queries(
                campaign_id=campaign.id,
                queries=queries,
                repository=repository,
            )
        propose_queries_fn = _queue_queries
    neighborhood_fn = (
        build_neighborhood_provider(repository=repository, campaign_id=campaign.id)
        if repository is not None
        else None
    )
    chatter_resolution = (
        resolve_catalog_route("chatter", repository=repository, campaign=campaign)
        if repository is not None
        else None
    )
    scientist_resolution = (
        resolve_catalog_route("scientist", repository=repository, campaign=campaign)
        if repository is not None
        else None
    )
    intent = await run_brain_b_designer(
        outline=outline,
        transcript_tail=transcript_tail,
        router=router,
        search_knowledge=search_fn,
        list_grounding_sources=lambda: grounding_sources,
        propose_outline_patch=_propose,
        propose_search_queries=propose_queries_fn,
        graph_neighborhood=neighborhood_fn,
        catalog_resolution=scientist_resolution,
    )

    working = (
        apply_outline_patch(outline, intent.outline_patch)
        if intent.outline_patch is not None
        else outline
    )

    chunks: list[str] = []
    async for token in stream_brain_a(
        role="mira-chatter",
        prompt_md_path=DESIGNER_BRAIN_A_PROMPT,
        transcript_tail=transcript_tail,
        brain_b_intent=intent,
        persona=persona,
        router=router,
        catalog_resolution=chatter_resolution,
    ):
        chunks.append(token)
    reply_text = "".join(chunks).strip()

    ready, unmet = is_ready_for_review(working, intent.ready_for_review)
    return DesignerTurnResult(
        reply_text=reply_text,
        brain_b_intent=intent,
        updated_outline=working,
        ready=ready,
        unmet=unmet,
    )
