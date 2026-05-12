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
from agentic_survey.llm.catalog import CatalogResolution

__all__ = [
    "BrainBToolBudgetExceeded",
    "filter_question_bank_for_role",
    "GraphNeighborhood",
    "InterviewerBrainBError",
    "SearchKnowledge",
    "run_brain_b_interviewer",
    "shortlist_question_bank_for_prompt",
]

SearchKnowledge = Callable[[str, int], Awaitable[list[dict[str, Any]]]]
GraphNeighborhood = Callable[..., Awaitable[dict[str, Any]]]

# Back-compat alias; the shared loop raises BrainBLoopError.
InterviewerBrainBError = BrainBLoopError

_QUESTION_SHORTLIST_LIMIT = 8
_CONTINUING_QUESTION_STATUSES = {"targeting", "partial"}


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
    enable_tools: bool = True,
    reasoning_budget_tokens: int | None = None,
    compact_context: bool = False,
    prior_active_axis_prefix: str = "",
    prior_consecutive_active_axis_count: int = 0,
    last_participant_message: str = "",
    participant_extracted_concepts: list[str] | None = None,
    catalog_resolution: CatalogResolution | None = None,
    campaign_id: str | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
) -> BrainBIntent:
    """Run Interviewer Brain B as a tool-calling agent.

    The Interviewer registry deliberately omits ``propose_outline_patch``
    because the outline is locked once the campaign goes LIVE, and every
    web-search surface because live interviews never call the network.
    Close authority stays with Brain B via ``should_close``; session
    signals are advisory and exposed through ``get_session_signals``.
    """
    sources_provider = list_grounding_sources or (lambda: [])
    tools = []
    if enable_tools:
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
    question_shortlist = shortlist_question_bank_for_prompt(
        eligible_questions,
        prior_question_coverage=prior_question_coverage,
        prior_axes_coverage=prior_axes_coverage,
        rubric_axes=list(outline.axes),
        active_axis_prefix=prior_active_axis_prefix,
        limit=_QUESTION_SHORTLIST_LIMIT,
    )

    outline_payload = (
        _compact_outline_for_prompt(outline)
        if compact_context
        else _outline_for_prompt(outline)
    )
    system_context = [
        "Current outline (JSON):\n" + json.dumps(outline_payload, indent=2),
        "Question shortlist (server-ranked candidate intents for this turn; the full eligible bank stays server-side):\n"
        + json.dumps(
            [_question_for_prompt(question) for question in question_shortlist],
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
    if prior_active_axis_prefix:
        system_context.append(
            "Axis rotation context (server tracks consecutive turns on the same axis):\n"
            + json.dumps(
                {
                    "prior_active_axis": prior_active_axis_prefix,
                    "consecutive_turns_on_prior_axis": prior_consecutive_active_axis_count,
                },
                indent=2,
            )
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
        minimum_close_coverage_axes=outline.rubric.minimum_close_coverage_axes,
        allow_under_minimum_close=_allow_under_minimum_close(session_signals),
        eligible_question_ids=eligible_question_ids,
        prior_question_coverage=prior_question_coverage,
        reasoning_budget_tokens=reasoning_budget_tokens,
        prior_active_axis_prefix=prior_active_axis_prefix,
        prior_consecutive_active_axis_count=prior_consecutive_active_axis_count,
        last_participant_message=last_participant_message,
        participant_extracted_concepts=participant_extracted_concepts,
        catalog_resolution=catalog_resolution,
        campaign_id=campaign_id,
        session_id=session_id,
        turn_id=turn_id,
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


def shortlist_question_bank_for_prompt(
    question_bank: list[SurveyQuestion],
    *,
    prior_question_coverage: list[QuestionCoverage] | None = None,
    prior_axes_coverage: list[AxisCoverage] | None = None,
    rubric_axes: list[str] | None = None,
    active_axis_prefix: str = "",
    limit: int = _QUESTION_SHORTLIST_LIMIT,
) -> list[SurveyQuestion]:
    """Return a small ranked question-intent set for Brain B's prompt.

    Role filtering has already happened before this helper runs. The shortlist
    keeps continuation questions visible, then spreads candidates across the
    lowest-covered rubric axes so Citadl does not dump the full instrument into
    every planning call.
    """
    if limit <= 0:
        return []
    questions = [question.model_copy(deep=True) for question in question_bank]
    if len(questions) <= limit:
        return questions

    prior_by_id = {entry.question_id: entry for entry in prior_question_coverage or []}
    score_by_axis = {
        _axis_prefix(entry.axis): max(0.0, min(1.0, entry.score))
        for entry in prior_axes_coverage or []
        if _axis_prefix(entry.axis)
    }
    axis_order = [_axis_prefix(axis) for axis in rubric_axes or []]
    axis_order = [axis for axis in axis_order if axis]
    axis_rank = {axis: index for index, axis in enumerate(axis_order)}
    original_index = {question.id: index for index, question in enumerate(questions)}

    selected: list[SurveyQuestion] = []
    selected_ids: set[str] = set()

    def add(question: SurveyQuestion | None) -> None:
        if question is None or question.id in selected_ids or len(selected) >= limit:
            return
        selected.append(question.model_copy(deep=True))
        selected_ids.add(question.id)

    def question_rank(question: SurveyQuestion) -> tuple[int, int, int]:
        prior = prior_by_id.get(question.id)
        status = prior.status if prior is not None else "pending"
        status_rank = {
            "targeting": 0,
            "partial": 1,
            "pending": 2,
            "skipped": 3,
            "satisfied": 4,
        }.get(status, 2)
        tier_rank = {"A": 0, "B": 1, "C": 2}.get((question.tier or "").upper(), 3)
        return (status_rank, tier_rank, original_index.get(question.id, 10_000))

    def best_for_axis(axis: str) -> SurveyQuestion | None:
        candidates = [
            question
            for question in questions
            if question.id not in selected_ids and _axis_prefix(question.axis_tag) == axis
        ]
        if not candidates:
            return None
        live_candidates = [
            question
            for question in candidates
            if prior_by_id.get(question.id, QuestionCoverage(question_id=question.id)).status
            not in {"satisfied", "skipped"}
        ]
        return min(live_candidates or candidates, key=question_rank)

    for question in sorted(
        questions,
        key=lambda q: (
            0
            if prior_by_id.get(q.id) is not None
            and prior_by_id[q.id].status in _CONTINUING_QUESTION_STATUSES
            else 1,
            question_rank(q),
        ),
    ):
        prior = prior_by_id.get(question.id)
        if prior is not None and prior.status in _CONTINUING_QUESTION_STATUSES:
            add(question)

    active_axis = _axis_prefix(active_axis_prefix)
    if active_axis:
        add(best_for_axis(active_axis))

    ranked_axes = sorted(
        {
            _axis_prefix(question.axis_tag)
            for question in questions
            if _axis_prefix(question.axis_tag)
        },
        key=lambda axis: (score_by_axis.get(axis, 0.0), axis_rank.get(axis, 10_000), axis),
    )
    for axis in ranked_axes:
        add(best_for_axis(axis))
        if len(selected) >= limit:
            break

    for question in sorted(questions, key=question_rank):
        add(question)
        if len(selected) >= limit:
            break

    return selected


def _axis_prefix(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    first = value.split(maxsplit=1)[0].strip("—:-. ")
    if len(first) >= 2 and first[0].upper() == "R" and first[1:].isdigit():
        return first.upper()
    return value


def _allow_under_minimum_close(session_signals: SessionSignals) -> bool:
    return bool(session_signals.participant_explicit_completion)


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


def _compact_outline_for_prompt(outline: OutlineArtifact) -> dict[str, Any]:
    return {
        "research_question": outline.research_question,
        "sampling_frame": outline.sampling_frame,
        "axes": list(outline.axes),
        "objectives": list(outline.objectives),
        "probes": list(outline.probes),
        "rubric": outline.rubric.model_dump(),
        "participant_faq": [entry.model_dump() for entry in outline.participant_faq],
    }


def _outline_for_prompt(outline: OutlineArtifact) -> dict[str, Any]:
    payload = outline.model_dump()
    payload.pop("question_bank", None)
    payload["question_bank_count"] = len(outline.question_bank)
    return payload
