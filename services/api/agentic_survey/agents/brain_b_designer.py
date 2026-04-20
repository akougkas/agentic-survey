from __future__ import annotations

from typing import Any, Awaitable, Callable

from agentic_survey.agents.brain_b_loop import (
    BrainBLoopError,
    BrainBToolBudgetExceeded,
    run_brain_b_with_tools,
)
from agentic_survey.agents.tools.definitions import (
    get_outline_state_tool,
    list_grounding_sources_tool,
    list_participant_faq_tool,
    propose_outline_patch_tool,
    search_knowledge_tool,
)
from agentic_survey.agents.tools.registry import ToolRegistry
from agentic_survey.domain.intent import BrainBIntent
from agentic_survey.domain.outline import OutlineArtifact

__all__ = [
    "BrainBToolBudgetExceeded",
    "DesignerBrainBError",
    "SearchKnowledge",
    "run_brain_b_designer",
]

SearchKnowledge = Callable[[str, int], Awaitable[list[dict[str, Any]]]]

# Back-compat alias: the shared loop raises BrainBLoopError. Existing callers
# (and tests) that import DesignerBrainBError keep working.
DesignerBrainBError = BrainBLoopError


async def run_brain_b_designer(
    *,
    outline: OutlineArtifact,
    transcript_tail: list[dict[str, Any]],
    router,
    search_knowledge: SearchKnowledge,
    list_grounding_sources: Callable[[], list[dict[str, Any]]],
    propose_outline_patch: Callable[[dict[str, Any]], None],
    max_tool_calls: int = 4,
) -> BrainBIntent:
    """Run Designer Brain B as a tool-calling agent.

    The caller provides closures for retrieval, grounding lookup, and patch
    capture. Brain B decides whether to invoke any of the registered tools
    before emitting its terminal ``BrainBIntent``. The returned intent's
    ``outline_patch`` is still the authoritative change set the caller
    applies; ``propose_outline_patch`` is an additional audit channel that
    captures mid-turn proposals.
    """
    registry = ToolRegistry(
        [
            search_knowledge_tool(search_fn=search_knowledge),
            get_outline_state_tool(outline_provider=lambda: outline),
            list_grounding_sources_tool(sources_provider=list_grounding_sources),
            list_participant_faq_tool(outline_provider=lambda: outline),
            propose_outline_patch_tool(patch_sink=propose_outline_patch),
        ]
    )
    system_context = [
        "Current outline (JSON):\n" + outline.model_dump_json(indent=2),
        "Approved grounding sources are available via list_grounding_sources.",
    ]
    result = await run_brain_b_with_tools(
        surface="designer",
        system_context=system_context,
        transcript_tail=transcript_tail,
        registry=registry,
        router=router,
        max_tool_calls=max_tool_calls,
    )
    return result.intent
