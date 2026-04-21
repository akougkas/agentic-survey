from __future__ import annotations

from typing import Any, Awaitable, Callable

from agentic_survey.agents.brain_b_loop import (
    BrainBLoopError,
    BrainBToolBudgetExceeded,
    run_brain_b_with_tools,
)
from agentic_survey.agents.tools.definitions import (
    get_graph_neighborhood_tool,
    get_outline_state_tool,
    get_session_signals_tool,
    list_grounding_sources_tool,
    list_participant_faq_tool,
    search_knowledge_tool,
)
from agentic_survey.agents.tools.registry import ToolRegistry
from agentic_survey.domain.intent import BrainBIntent
from agentic_survey.domain.outline import OutlineArtifact
from agentic_survey.engine.session_policy import SessionSignals

__all__ = [
    "BrainBToolBudgetExceeded",
    "GraphNeighborhood",
    "InterviewerBrainBError",
    "SearchKnowledge",
    "run_brain_b_interviewer",
]

SearchKnowledge = Callable[[str, int], Awaitable[list[dict[str, Any]]]]
GraphNeighborhood = Callable[..., Awaitable[dict[str, Any]]]

# Back-compat alias; the shared loop raises BrainBLoopError.
InterviewerBrainBError = BrainBLoopError


async def run_brain_b_interviewer(
    *,
    outline: OutlineArtifact,
    transcript_tail: list[dict[str, Any]],
    session_signals: SessionSignals,
    router,
    search_knowledge: SearchKnowledge,
    list_grounding_sources: Callable[[], list[dict[str, Any]]] | None = None,
    graph_neighborhood: GraphNeighborhood | None = None,
    max_tool_calls: int = 4,
    participant_context: dict[str, str] | None = None,
) -> BrainBIntent:
    """Run Interviewer Brain B as a tool-calling agent.

    The Interviewer registry deliberately omits ``propose_outline_patch``
    because the outline is locked once the campaign goes LIVE, and every
    web-search surface because live interviews never call the network.
    Close authority stays with Brain B via ``should_close``; session
    signals are advisory and exposed through ``get_session_signals``.
    """
    sources_provider = list_grounding_sources or (lambda: [])
    tools = [
        search_knowledge_tool(search_fn=search_knowledge),
        get_outline_state_tool(outline_provider=lambda: outline),
        list_grounding_sources_tool(sources_provider=sources_provider),
        list_participant_faq_tool(outline_provider=lambda: outline),
        get_session_signals_tool(signals_provider=lambda: session_signals),
    ]
    if graph_neighborhood is not None:
        tools.append(get_graph_neighborhood_tool(neighborhood_fn=graph_neighborhood))
    registry = ToolRegistry(tools)
    system_context = [
        "Current outline (JSON):\n" + outline.model_dump_json(indent=2),
        "Session signals (advisory; close is still your call):\n"
        + session_signals.model_dump_json(indent=2),
    ]
    context_lines: list[str] = []
    if participant_context:
        for key, raw_value in participant_context.items():
            if not isinstance(raw_value, str):
                continue
            value = raw_value.strip()
            if not value:
                continue
            context_lines.append(f'- {key}: "{value}"')
    if context_lines:
        system_context.append(
            "Participant self-description (from pre-interview micro-form):\n"
            + "\n".join(context_lines)
        )
    result = await run_brain_b_with_tools(
        surface="interviewer",
        system_context=system_context,
        transcript_tail=transcript_tail,
        registry=registry,
        router=router,
        max_tool_calls=max_tool_calls,
    )
    return result.intent
