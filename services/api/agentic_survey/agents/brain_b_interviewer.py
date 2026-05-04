from __future__ import annotations

import json
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
from agentic_survey.domain.intent import AxisCoverage, BrainBIntent, QuestionCoverage
from agentic_survey.domain.outline import OutlineArtifact, SurveyQuestion
from agentic_survey.engine.session_policy import SessionSignals

__all__ = [
    "BrainBToolBudgetExceeded",
    "filter_question_bank_for_role",
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
    prior_axes_coverage: list[AxisCoverage] | None = None,
    eligible_question_ids: list[str] | None = None,
    prior_question_coverage: list[QuestionCoverage] | None = None,
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
    role_self_description = ""
    if participant_context:
        raw_role = participant_context.get("role_self_description", "")
        if isinstance(raw_role, str):
            role_self_description = raw_role.strip()
    eligible_questions = filter_question_bank_for_role(
        outline.question_bank,
        role_self_description,
    )
    if eligible_question_ids is None:
        eligible_question_ids = [question.id for question in eligible_questions]

    system_context = [
        "Current outline (JSON):\n" + outline.model_dump_json(indent=2),
        "Question bank (eligible questions for this respondent):\n"
        + json.dumps(
            [_question_for_prompt(question) for question in eligible_questions],
            indent=2,
        ),
        "Prior question coverage (server enforces monotonicity):\n"
        + json.dumps(
            [entry.model_dump() for entry in prior_question_coverage or []],
            indent=2,
        ),
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
    if prior_axes_coverage:
        system_context.append(
            "Prior axes coverage (monotonicity floor; enforced server-side):\n"
            + json.dumps([c.model_dump() for c in prior_axes_coverage], indent=2)
        )
    result = await run_brain_b_with_tools(
        surface="interviewer",
        system_context=system_context,
        transcript_tail=transcript_tail,
        registry=registry,
        router=router,
        max_tool_calls=max_tool_calls,
        rubric_axes=list(outline.axes),
        prior_axes_coverage=prior_axes_coverage,
        close_guard_axes=list(outline.rubric.mandatory_close_axes),
        eligible_question_ids=eligible_question_ids,
        prior_question_coverage=prior_question_coverage,
    )
    return result.intent


def filter_question_bank_for_role(
    question_bank: list[SurveyQuestion],
    role_self_description: str | None,
) -> list[SurveyQuestion]:
    """Return questions whose role routing applies to this respondent.

    An empty or missing role keeps the full bank so Brain B is not forced into
    a false negative before the participant has supplied or corrected the
    micro-form role.
    """
    role = (role_self_description or "").strip()
    if not role:
        return [question.model_copy(deep=True) for question in question_bank]
    eligible: list[SurveyQuestion] = []
    for question in question_bank:
        roles = [item.strip() for item in question.applies_to_roles if item.strip()]
        if not roles or role in roles:
            eligible.append(question.model_copy(deep=True))
    return eligible


def _question_for_prompt(question: SurveyQuestion) -> dict[str, Any]:
    return {
        "id": question.id,
        "prompt": question.prompt,
        "axis_tag": question.axis_tag,
        "notes": question.notes,
        "follow_up_hints": list(question.follow_up_hints),
        "saturation_signals": list(question.saturation_signals),
        "leading_language_avoid": list(question.leading_language_avoid),
    }
