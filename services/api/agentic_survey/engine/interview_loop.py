from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agentic_survey.agents.brain_a import build_scaffold_intent, stream_brain_a
from agentic_survey.agents.brain_b_interviewer import (
    InterviewerBrainBError,
    filter_question_bank_for_role,
    run_brain_b_interviewer,
)
from agentic_survey.agents.brain_b_loop import _apply_closing_prose_guard
from agentic_survey.agents.validator import Validator
from agentic_survey.domain.intent import AxisCoverage, BrainBIntent, QuestionCoverage
from agentic_survey.engine.graph_builder import apply_validator_to_graph

if TYPE_CHECKING:
    from agentic_survey.engine.event_bus import CampaignEventBus
from agentic_survey.engine.retrieval_cache import RetrievalCache
from agentic_survey.engine.session_policy import (
    SessionSignals,
    compute_signals,
    derive_objective_tags,
)
from agentic_survey.llm.client import resolve_catalog_route
from agentic_survey.llm.router import LiteLLMRouter
from agentic_survey.llm.reasoning import (
    apply_reasoning_settings,
    preplan_reasoning_budget_tokens,
    set_lmstudio_thinking,
    visible_reply_max_tokens,
)
from agentic_survey.repository import (
    Campaign,
    InMemoryRepository,
    InterviewSessionRecord,
    InterviewTurnRecord,
    ParticipantControl,
)
from agentic_survey.services.graph import build_neighborhood_provider
from agentic_survey.services.retrieval import build_search_knowledge

__all__ = [
    "CONTROL_INPUTS",
    "InterviewEvent",
    "InterviewTurnResult",
    "InterviewerBrainBError",
    "INTERVIEWER_BRAIN_A_PROMPT",
    "normalize_control_signal",
    "opening_turn_message",
    "run_interview_turn",
    "run_post_turn_background",
    "run_pre_plan_background",
]

logger = logging.getLogger(__name__)


def opening_turn_message(campaign: Campaign, session: InterviewSessionRecord) -> str:
    """The first agent turn at the top of a participant session.

    Three beats, deterministic (no LLM) so a session boots cleanly even
    when the router is cold:

    1. Greeting and role-aware purpose. When the participant picked a role
       at intake, the greeting calls it out so the conversation lands as
       "with someone who's done what you do," not as a generic survey.
    2. Orientation. Names the axis count, time bound, consent posture,
       and the four control verbs (skip, pause, come back, stop).
    3. Soft opener. Echoes ``evidence_of_belonging`` when present and
       invites one concrete moment. If the participant skipped the
       optional role question, the opener asks it back in plain language
       instead of fabricating one. Never the R-axis probe — Brain B fires
       those after the participant answers this.

    The micro-form answer is written in first person ("I run …"); the
    opener pivots it to second person before quoting so Mira doesn't
    sound like she is talking about herself. ``run_interview_turn`` takes
    over from turn 2 onward.
    """
    answers = getattr(session, "micro_form_answers", {}) or {}
    evidence = (answers.get("evidence_of_belonging") or "").strip()
    role_self_description = (answers.get("role_self_description") or "").strip()
    consent_mode = getattr(session, "consent_mode", "anonymous")
    axis_count = sum(1 for axis in (campaign.outline.axes or []) if axis and axis.strip())

    role_phrase = _role_phrase_for_opener(role_self_description)
    if role_phrase:
        greeting = (
            f"Welcome. I'm Mira, here to learn how {role_phrase} actually work with data day-to-day."
        )
    else:
        greeting = "Welcome. I'm Mira."

    axes_word = _axis_count_word(axis_count)
    if consent_mode == "named":
        consent_phrase = "Your responses can be attributed to you, as you chose at intake."
    else:
        consent_phrase = "Your responses stay anonymous."
    controls = "You can skip, pause, come back later, or stop anytime."
    orientation = (
        f"We'll move through {axes_word} short topic threads at whatever depth "
        f"your time allows. {consent_phrase} {controls}"
    )

    if evidence:
        noun_phrase = _extract_noun_phrase(evidence)
        opener = (
            f"To start: you mentioned {noun_phrase}. "
            "What does a typical day with that look like for you these days?"
        )
    elif not role_self_description:
        opener = (
            "To start: in a sentence, what kind of work brings you in front of "
            "scientific or research data?"
        )
    else:
        opener = (
            "To start: what does a recent ordinary day with data look like for you?"
        )

    return f"{greeting} {orientation} {opener}"


# Mapping the optional intake role to a peer-style noun the greeting can use.
# Empty result means the opener falls back to the role-less greeting; that
# avoids fabricating a role for the "Other or multiple" path or for
# participants who skipped the optional question entirely.
_ROLE_PHRASE_BY_OPTION: dict[str, str] = {
    "Research scientist or engineer generating or analyzing data": "scientists like you",
    "Facility operator or systems administrator": "facility operators like you",
    "Tool, library, or service developer": "tool builders like you",
    "Research software engineer supporting scientific applications": "research software engineers like you",
    "AI or ML researcher or practitioner": "ML researchers like you",
    "Institutional or platform lead": "platform leads like you",
}


def _role_phrase_for_opener(role_self_description: str) -> str:
    cleaned = role_self_description.strip()
    if not cleaned:
        return ""
    return _ROLE_PHRASE_BY_OPTION.get(cleaned, "")


_AXIS_COUNT_WORDS: dict[int, str] = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
}


def _axis_count_word(count: int) -> str:
    if count <= 0:
        return "a handful of"
    if count in _AXIS_COUNT_WORDS:
        return _AXIS_COUNT_WORDS[count]
    return str(count)


# Pivot table: first-person pronouns and contractions in a micro-form answer
# get rewritten as second-person before the opener quotes them. Order matters:
# longer multi-word phrases run first so contractions like "I'm" don't get
# eaten by a bare-"i" rule. Bare "i" / "we" / "us" / "my" / "me" / "mine"
# / "myself" / "ours" only fire on whole-word boundaries so proper nouns
# like ``Slurm`` or domain terms like ``MIME`` survive untouched.
_PRONOUN_PIVOTS: tuple[tuple[str, str], ...] = (
    ("i'm", "you're"),
    ("i've", "you've"),
    ("i'd", "you'd"),
    ("i'll", "you'll"),
    ("we're", "your team is"),
    ("we've", "your team has"),
    ("we'd", "your team would"),
    ("we'll", "your team will"),
    ("our", "your"),
    ("ours", "yours"),
    ("us", "your team"),
    ("we", "your team"),
    ("my", "your"),
    ("mine", "yours"),
    ("me", "you"),
    ("myself", "yourself"),
    ("i", "you"),
)

_PRONOUN_PIVOT_RE = re.compile(
    r"(?i)\b(" + "|".join(re.escape(src) for src, _ in _PRONOUN_PIVOTS) + r")\b"
)
_PRONOUN_PIVOT_LOOKUP: dict[str, str] = {src: dst for src, dst in _PRONOUN_PIVOTS}


def _match_case(token: str, replacement: str) -> str:
    """Project the casing of ``token`` onto ``replacement``.

    Handles three patterns: all lower, all upper, and capitalized first
    letter. Single-character tokens (notably ``"I"``) are treated as
    capitalized rather than fully upper since the bare pronoun is always
    written that way in English; treating it as an acronym would shout
    ``YOU`` back at the participant. Anything else falls through to
    lowercase.
    """
    if not replacement:
        return replacement
    if len(token) > 1 and token.isupper():
        return replacement.upper()
    if token[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _pivot_to_second_person(text: str) -> str:
    """Rewrite first-person pronouns to second-person inside a quoted phrase.

    The micro-form answer is the participant's own self-description ("I
    run cryo-EM…", "We operate a tape archive…"). The opener wraps it in
    "You mentioned <phrase>"; quoting the phrase verbatim makes Mira
    appear to be claiming the work as hers. We rewrite first-person tokens
    to second-person on whole-word boundaries so proper nouns like
    ``Slurm`` and acronyms keep their original casing.
    """
    if not text:
        return text

    def _swap(match: "re.Match[str]") -> str:
        token = match.group(0)
        replacement = _PRONOUN_PIVOT_LOOKUP.get(token.lower(), token)
        return _match_case(token, replacement)

    return _PRONOUN_PIVOT_RE.sub(_swap, text)


def _extract_noun_phrase(text: str, *, max_words: int = 12) -> str:
    """Pull a short head-of-sentence phrase from free text.

    Naive slice: the first clause before a comma, or the first
    ``max_words`` tokens. Trailing punctuation is stripped. The result is
    pivoted to second person so the opener can quote it inside "You
    mentioned …" without making Mira sound like she did the work herself.
    This runs deterministically on the respondent's own words; no LLM call.

    The first character is lowercased after pivoting because the opener
    embeds the phrase mid-sentence ("You mentioned <phrase>") — keeping
    the leading "I"/"We"/etc. as a sentence-initial capital after pivot
    would produce a stilted "You mentioned You run …".
    """
    cleaned = text.strip()
    if not cleaned:
        return ""
    head = cleaned.split(",", 1)[0].strip()
    tokens = head.split()
    if len(tokens) > max_words:
        head = " ".join(tokens[:max_words])
    head = head.rstrip(".!?;:").strip()
    pivoted = _pivot_to_second_person(head)
    if pivoted and pivoted[:1].isupper():
        pivoted = pivoted[:1].lower() + pivoted[1:]
    return pivoted

INTERVIEWER_BRAIN_A_PROMPT = "interviewer_brain_a.md"


CONTROL_INPUTS: dict[ParticipantControl, set[str]] = {
    "pause": {"pause", "pause for now", "pause here", "lets pause", "let us pause"},
    "skip": {"skip", "skip this", "id rather skip this", "pass on this"},
    "continue": {"continue", "keep going", "lets keep going", "i can keep going"},
    "stop": {"stop", "stop here", "end this", "end here", "i want to stop", "im done"},
}


def _normalize_phrase(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]+", "", text.strip().lower())
    return " ".join(cleaned.split())


def normalize_control_signal(text: str) -> ParticipantControl | None:
    cleaned = _normalize_phrase(text)
    if not cleaned:
        return None
    for control, phrases in CONTROL_INPUTS.items():
        if cleaned in phrases:
            return control
    return None


@dataclass(slots=True)
class InterviewEvent:
    """One entry in the ordered SSE event log produced by ``run_interview_turn``.

    ``name`` maps 1:1 to lifecycles.md §2.7 SSE names. Foreground-only
    names now: ``turn_start``, ``token``, ``get_user_input``,
    ``turn_complete``, ``session_paused``, ``session_finished``. Events
    produced by the post-turn background task (``validator_scored``,
    ``graph_delta``, ``concepts_extracted``, ``brain_b_planned``) are
    published directly to the bus and never enter the foreground list.
    """

    name: str
    data: dict[str, Any]


@dataclass(slots=True)
class InterviewTurnResult:
    session: InterviewSessionRecord
    agent_turn: InterviewTurnRecord | None = None
    participant_turn: InterviewTurnRecord | None = None
    brain_b_intent: BrainBIntent | None = None
    signals: SessionSignals | None = None
    close_reason: str | None = None
    events: list[InterviewEvent] = field(default_factory=list)


async def run_interview_turn(
    *,
    session_id: str,
    participant_content: str,
    chip_selected: str | None,
    repository: InMemoryRepository,
    validator: Validator,
    router: LiteLLMRouter,
    cache: RetrievalCache,
) -> InterviewTurnResult:
    """Run one participant turn in the **foreground**.

    Brain A streams here; Validator, graph builder, and Brain B are
    deferred to :func:`run_post_turn_background`. Foreground steps:

    1. Persist the participant turn (with a control-signal payload for
       control words or a skeletal ``pending_validation`` marker for
       substantive turns; the background task fills in validator
       results).
    2. Handle control signals (``pause``/``stop`` short-circuit here,
       ``skip``/``continue`` fall through to streaming).
    3. Read ``session.next_plan`` (set by the previous turn's background
       task). If present, consume it; otherwise synthesize a
       :func:`build_scaffold_intent` so Brain A still has something to
       render.
    4. Stream Brain A's reply tokens.
    5. Persist the agent turn with the intent that drove it.

    ``cache`` is passed through for signature symmetry with the
    background runner; it is only consumed when real retrieval fires,
    which is always a Brain B concern.
    """
    del cache  # foreground does not touch retrieval today; kept for API parity.
    session = repository.get_interview_session(session_id)
    if session is None:
        raise ValueError(f"Interview session {session_id!r} not found")
    campaign = repository.get_campaign(session.campaign_id)
    if campaign is None:
        raise ValueError(f"Campaign {session.campaign_id!r} not found for session {session_id!r}")

    events: list[InterviewEvent] = [
        InterviewEvent(name="turn_start", data={"session_id": session.id}),
    ]

    content = participant_content.strip()
    control = normalize_control_signal(content)

    if control in {"pause", "skip", "continue", "stop"}:
        validation_payload: dict[str, Any] = {
            "control_signal": control,
            "objective_tags": [],
        }
        if chip_selected:
            validation_payload["chip_selected"] = chip_selected
    else:
        # Validator runs in the background. Persist a placeholder so the
        # turn row isn't ``None``; ``derive_objective_tags`` fires later.
        validation_payload = {
            "pending_validation": True,
            "objective_tags": [],
        }
        if chip_selected:
            validation_payload["chip_selected"] = chip_selected

    participant_turn = repository.append_interview_turn(
        session.id,
        role="participant",
        content=content,
        validation=validation_payload,
    )

    if control == "pause":
        paused = repository.pause_interview_session(session.id, reason="participant_paused")
        events.append(
            InterviewEvent(
                name="session_paused",
                data={"session_id": paused.id, "reason": "participant_paused"},
            )
        )
        return InterviewTurnResult(
            session=paused,
            participant_turn=participant_turn,
            events=events,
        )

    refreshed = repository.get_interview_session(session.id)
    assert refreshed is not None

    if control == "stop":
        close_reason = "participant_stop"
        reply_text = await _stream_closing(
            router=router,
            session=refreshed,
            campaign=campaign,
            close_reason=close_reason,
            events=events,
            repository=repository,
        )
        agent_turn = repository.append_interview_turn(
            refreshed.id,
            role="agent",
            content=reply_text,
            brain_b_intent=None,
            get_user_input=None,
            validation={
                "closing": True,
                "close_reason": close_reason,
            },
        )
        finished = repository.finish_interview_session(refreshed.id, close_reason=close_reason)
        events.append(
            InterviewEvent(
                name="turn_complete",
                data={"session_id": finished.id, "turn_id": agent_turn.id},
            )
        )
        events.append(
            InterviewEvent(
                name="session_finished",
                data={"session_id": finished.id, "close_reason": close_reason},
            )
        )
        return InterviewTurnResult(
            session=finished,
            agent_turn=agent_turn,
            participant_turn=participant_turn,
            signals=None,
            close_reason=close_reason,
            events=events,
        )

    # Substantive / skip / continue: render Brain A from the plan the
    # previous background task wrote (or a scaffold when no plan exists).
    planned = refreshed.next_plan
    if planned is not None:
        planner_source = "brain_b"
        intent = planned.model_copy(deep=True)
        # Consume the plan so a subsequent failed background leaves the
        # NEXT turn on scaffold instead of rendering a stale probe.
        repository.update_next_plan(refreshed.id, None)
    else:
        planner_source = "scaffold"
        intent = build_scaffold_intent(
            outline=campaign.outline,
            participant_context=dict(refreshed.micro_form_answers or {}),
            transcript_tail=_transcript_tail(refreshed),
        )

    persona = _compose_persona(campaign.outline.persona_hints)
    chatter_resolution = resolve_catalog_route(
        "chatter", repository=repository, campaign=campaign
    )
    chunks: list[str] = []
    async for token in stream_brain_a(
        role="mira-chatter",
        prompt_md_path=INTERVIEWER_BRAIN_A_PROMPT,
        transcript_tail=_transcript_tail(refreshed),
        brain_b_intent=intent,
        persona=persona,
        router=router,
        participant_context=dict(refreshed.micro_form_answers or {}),
        catalog_resolution=chatter_resolution,
    ):
        chunks.append(token)
        events.append(InterviewEvent(name="token", data={"text": token}))

    reply_text = "".join(chunks).strip()
    intent = _apply_closing_prose_guard(intent, reply_text=reply_text)

    agent_turn = repository.append_interview_turn(
        refreshed.id,
        role="agent",
        content=reply_text,
        brain_b_intent=intent,
        get_user_input=intent.get_user_input,
        validation={"planner_source": planner_source},
    )
    events.append(
        InterviewEvent(
            name="get_user_input",
            data={
                "session_id": refreshed.id,
                "turn_id": agent_turn.id,
                "question": intent.get_user_input.question,
                "options": list(intent.get_user_input.options),
                "allow_free_text": intent.get_user_input.allow_free_text,
            },
        )
    )
    events.append(
        InterviewEvent(
            name="turn_complete",
            data={"session_id": refreshed.id, "turn_id": agent_turn.id},
        )
    )

    updated_session = repository.get_interview_session(refreshed.id)
    assert updated_session is not None
    return InterviewTurnResult(
        session=updated_session,
        agent_turn=agent_turn,
        participant_turn=participant_turn,
        brain_b_intent=intent,
        signals=None,
        events=events,
    )


async def run_post_turn_background(
    *,
    session_id: str,
    campaign_id: str,
    participant_turn_id: str,
    agent_turn_id: str,
    repository: InMemoryRepository,
    router: LiteLLMRouter,
    validator: Validator,
    cache: RetrievalCache,
    bus: "CampaignEventBus",
) -> None:
    """Post-turn fan-out: Validator → graph → Brain B → next_plan.

    Spawned by the HTTP handler under ``asyncio.create_task`` after the
    foreground returns its payload. Runs entirely under an outer guard:
    any exception is logged and recorded on the agent turn's validation
    dict as ``background_failed=True``; the exception is never raised to
    the caller or the event loop's default handler.

    Ordering (each step emits exactly one bus event on success):

    1. Validator scores the participant turn →
       publishes ``validator_scored`` and merges the result into the
       participant turn's ``validation``.
    2. :func:`apply_validator_to_graph` writes concepts + edges →
       publishes ``graph_delta`` and ``concepts_extracted``.
    3. :func:`run_brain_b_interviewer` plans the NEXT probe and the plan
       is written via ``repository.update_next_plan`` →
       publishes ``brain_b_planned``.

    Control-signal turns (``skip``/``continue``) skip steps 1 and 2 since
    there is no substantive participant content to score.
    """
    try:
        await _post_turn_background_inner(
            session_id=session_id,
            campaign_id=campaign_id,
            participant_turn_id=participant_turn_id,
            agent_turn_id=agent_turn_id,
            repository=repository,
            router=router,
            validator=validator,
            cache=cache,
            bus=bus,
        )
    except Exception:
        logger.exception(
            "post-turn background failed: session=%s participant_turn=%s agent_turn=%s",
            session_id,
            participant_turn_id,
            agent_turn_id,
        )
        try:
            repository.update_interview_turn_validation(
                session_id,
                agent_turn_id,
                {"background_failed": True},
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "post-turn background failed to record background_failed marker"
            )


async def _post_turn_background_inner(
    *,
    session_id: str,
    campaign_id: str,
    participant_turn_id: str,
    agent_turn_id: str,
    repository: InMemoryRepository,
    router: LiteLLMRouter,
    validator: Validator,
    cache: RetrievalCache,
    bus: "CampaignEventBus",
) -> None:
    session = repository.get_interview_session(session_id)
    if session is None:
        raise RuntimeError(f"post-turn background: session {session_id!r} not found")
    campaign = repository.get_campaign(session.campaign_id)
    if campaign is None:
        raise RuntimeError(
            f"post-turn background: campaign {session.campaign_id!r} not found"
        )

    participant_turn = next(
        (turn for turn in session.turns if turn.id == participant_turn_id),
        None,
    )
    if participant_turn is None:
        raise RuntimeError(
            f"post-turn background: participant turn {participant_turn_id!r} missing"
        )

    existing_validation = participant_turn.validation or {}
    validation_payload: dict[str, Any] = existing_validation
    is_control = "control_signal" in existing_validation

    # Step 1: Validator.
    if not is_control:
        last_agent = _last_agent_content_before(session, participant_turn_id)
        result = await validator.validate(
            campaign=campaign,
            content=participant_turn.content,
            outline=campaign.outline,
            previous_agent_question=last_agent,
        )
        validation_payload = result.to_dict()
        validation_payload["objective_tags"] = derive_objective_tags(
            content=participant_turn.content,
            outline=campaign.outline,
            validation=validation_payload,
        )
        # Preserve chip_selected if the foreground recorded one.
        if "chip_selected" in existing_validation:
            validation_payload["chip_selected"] = existing_validation["chip_selected"]
        repository.update_interview_turn_validation(
            session_id,
            participant_turn_id,
            validation_payload,
        )
        bus.publish_many(
            campaign_id,
            [
                InterviewEvent(
                    name="validator_scored",
                    data={
                        "session_id": session_id,
                        "turn_id": participant_turn_id,
                        "validation": validation_payload,
                    },
                )
            ],
        )

        # Step 2: graph builder.
        delta = await apply_validator_to_graph(
            campaign_id=campaign_id,
            session_id=session_id,
            turn_id=participant_turn_id,
            validation=validation_payload,
            repository=repository,
            router=router,
        )
        delta_payload = delta.to_dict()
        delta_payload["session_id"] = session_id
        delta_payload["turn_id"] = participant_turn_id
        concept_payload = {
            "session_id": session_id,
            "turn_id": participant_turn_id,
            "concepts": [
                {"id": node["id"], "label": node["label"], "type": node.get("type", "")}
                for node in delta.add_nodes
            ],
            "light_up": list(delta.light_up),
        }
        bus.publish_many(
            campaign_id,
            [
                InterviewEvent(name="graph_delta", data=delta_payload),
                InterviewEvent(name="concepts_extracted", data=concept_payload),
            ],
        )

    # Step 3: Brain B plans the NEXT turn.
    refreshed = repository.get_interview_session(session_id)
    assert refreshed is not None
    if not _should_plan_after_participant_turn(
        refreshed,
        participant_turn_id=participant_turn_id,
    ):
        return
    participant_validations = [
        turn.validation for turn in refreshed.turns if turn.role == "participant"
    ]
    signals = compute_signals(refreshed, campaign.outline, participant_validations)
    prior_axes = _last_axes_coverage(refreshed)
    prior_question_coverage = _last_question_coverage(refreshed)
    prior_active_axis_prefix, prior_consecutive_active_axis_count = (
        _consecutive_active_axis_history(refreshed)
    )
    last_participant_message, participant_extracted_concepts = (
        _last_participant_grounding(refreshed)
    )
    transcript_tail = _transcript_tail(refreshed)
    search_fn = build_search_knowledge(
        repository=repository,
        campaign_id=campaign_id,
        surface="interviewer",
        router=router,
        session_id=session_id,
        cache=cache,
    )
    neighborhood_fn = build_neighborhood_provider(
        repository=repository,
        campaign_id=campaign_id,
    )
    grounding_snapshot = _list_approved_grounding_sources(repository, campaign_id)
    participant_context = dict(refreshed.micro_form_answers or {})
    planning_outline = _role_filtered_outline(campaign.outline, participant_context)
    eligible_question_ids = [question.id for question in planning_outline.question_bank]
    scientist_resolution = resolve_catalog_route(
        "scientist", repository=repository, campaign=campaign
    )
    intent = await run_brain_b_interviewer(
        outline=planning_outline,
        transcript_tail=transcript_tail,
        session_signals=signals,
        router=router,
        search_knowledge=search_fn,
        list_grounding_sources=lambda: grounding_snapshot,
        graph_neighborhood=neighborhood_fn,
        participant_context=participant_context,
        prior_axes_coverage=prior_axes,
        eligible_question_ids=eligible_question_ids,
        prior_question_coverage=prior_question_coverage,
        prior_active_axis_prefix=prior_active_axis_prefix,
        prior_consecutive_active_axis_count=prior_consecutive_active_axis_count,
        last_participant_message=last_participant_message,
        participant_extracted_concepts=participant_extracted_concepts,
        catalog_resolution=scientist_resolution,
    )
    intent = _attach_question_coverage_turn_ids(
        intent,
        prior_question_coverage=prior_question_coverage,
        participant_turn_id=participant_turn_id,
    )
    intent = _floor_answered_axis_from_validator(
        intent,
        answered_axis_prefix=_answered_axis_prefix_for_agent_turn(
            refreshed,
            agent_turn_id=agent_turn_id,
        ),
        validation=validation_payload,
    )
    latest = repository.get_interview_session(session_id)
    if latest is None or not _should_plan_after_participant_turn(
        latest,
        participant_turn_id=participant_turn_id,
    ):
        return
    repository.update_next_plan(session_id, intent)
    _persist_question_answers(
        repository=repository,
        campaign_id=campaign_id,
        session_id=session_id,
        participant_turn_id=participant_turn_id,
        prior_question_coverage=prior_question_coverage,
        intent=intent,
    )
    bus.publish_many(
        campaign_id,
        [
            InterviewEvent(
                name="brain_b_planned",
                data={
                    "session_id": session_id,
                    "next_plan": intent.model_dump(mode="json"),
                },
            )
        ],
    )


_AXIS_PREFIX_RE = re.compile(r"^(R\d+)", re.IGNORECASE)
_ANSWERED_AXIS_FLOOR = 0.20


def _axis_prefix(value: str) -> str:
    match = _AXIS_PREFIX_RE.match((value or "").strip())
    if match:
        return match.group(1).upper()
    return ""


def _answered_axis_prefix_for_agent_turn(
    session: InterviewSessionRecord,
    *,
    agent_turn_id: str,
) -> str:
    for turn in session.turns:
        if turn.id != agent_turn_id:
            continue
        intent = turn.brain_b_intent
        if intent is None:
            return ""
        return _axis_prefix(intent.active_axis)
    return ""


def _validator_found_substantive_evidence(validation: dict[str, Any]) -> bool:
    if validation.get("control_signal"):
        return False
    if bool(validation.get("is_spam")):
        return False
    for key in ("coverage_score", "quality_score"):
        try:
            if float(validation.get(key) or 0.0) > 0.0:
                return True
        except (TypeError, ValueError):
            continue
    concepts = validation.get("extracted_concepts") or []
    return bool(concepts)


def _floor_answered_axis_from_validator(
    intent: BrainBIntent,
    *,
    answered_axis_prefix: str,
    validation: dict[str, Any],
    floor: float = _ANSWERED_AXIS_FLOOR,
) -> BrainBIntent:
    target_axis_prefix = answered_axis_prefix or _axis_prefix(intent.active_axis)
    if not target_axis_prefix:
        return intent
    if not _validator_found_substantive_evidence(validation):
        return intent
    updated_axes: list[AxisCoverage] = []
    bumped = False
    for entry in intent.axes_coverage:
        if _axis_prefix(entry.axis) == target_axis_prefix and entry.score < floor:
            updated_axes.append(entry.model_copy(update={"score": floor}))
            bumped = True
        else:
            updated_axes.append(entry)
    if not bumped:
        return intent
    logger.warning(
        "brain_b axes_coverage floor-bumped answered axis axis=%s floor=%s",
        target_axis_prefix,
        floor,
    )
    return intent.model_copy(update={"axes_coverage": updated_axes})


def _latest_participant_turn_id(session: InterviewSessionRecord) -> str:
    for turn in reversed(session.turns):
        if turn.role == "participant":
            return turn.id
    return ""


def _should_plan_after_participant_turn(
    session: InterviewSessionRecord,
    *,
    participant_turn_id: str,
) -> bool:
    latest_participant_turn_id = _latest_participant_turn_id(session)
    if latest_participant_turn_id != participant_turn_id:
        logger.info(
            "post-turn brain_b skipped stale participant turn: session=%s participant_turn=%s latest_participant_turn=%s",
            session.id,
            participant_turn_id,
            latest_participant_turn_id or "<none>",
        )
        return False
    if session.status != "active":
        logger.info(
            "post-turn brain_b skipped inactive session: session=%s participant_turn=%s status=%s",
            session.id,
            participant_turn_id,
            session.status,
        )
        return False
    return True


async def run_pre_plan_background(
    *,
    session_id: str,
    campaign_id: str,
    repository: InMemoryRepository,
    router: LiteLLMRouter,
    cache: RetrievalCache,
    bus: "CampaignEventBus",
) -> None:
    """Seed ``session.next_plan`` before the first participant turn.

    Invite redemption schedules this against the fresh session, where the
    transcript tail is empty and participant context comes from the
    micro-form. ``POST /sessions/{sid}/start`` may also schedule it after
    the deterministic opener. Same isolation contract as the post-turn
    runner: any exception is swallowed and logged; the next turn degrades
    cleanly to a scaffold.
    """
    try:
        logger.info(
            "pre-plan background started: session=%s campaign=%s",
            session_id,
            campaign_id,
        )
        session = repository.get_interview_session(session_id)
        if session is None:
            repository.update_preplan_status(
                session_id,
                status="failed",
                error_detail="session not found at warmup start",
            )
            return
        campaign = repository.get_campaign(session.campaign_id)
        if campaign is None:
            repository.update_preplan_status(
                session_id,
                status="failed",
                error_detail=f"campaign {session.campaign_id!r} not found at warmup start",
            )
            return
        transcript_tail = _transcript_tail(session)
        signals = compute_signals(session, campaign.outline, [])
        prior_question_coverage = _last_question_coverage(session)
        search_fn = build_search_knowledge(
            repository=repository,
            campaign_id=campaign_id,
            surface="interviewer",
            router=router,
            session_id=session_id,
            cache=cache,
        )
        neighborhood_fn = build_neighborhood_provider(
            repository=repository,
            campaign_id=campaign_id,
        )
        grounding_snapshot = _list_approved_grounding_sources(repository, campaign_id)
        participant_context = dict(session.micro_form_answers or {})
        planning_outline = _role_filtered_outline(campaign.outline, participant_context)
        eligible_question_ids = [question.id for question in planning_outline.question_bank]
        scientist_resolution = resolve_catalog_route(
            "scientist", repository=repository, campaign=campaign
        )
        intent = await run_brain_b_interviewer(
            outline=planning_outline,
            transcript_tail=transcript_tail,
            session_signals=signals,
            router=router,
            search_knowledge=search_fn,
            list_grounding_sources=lambda: grounding_snapshot,
            graph_neighborhood=neighborhood_fn,
            participant_context=participant_context,
            prior_axes_coverage=[],
            eligible_question_ids=eligible_question_ids,
            prior_question_coverage=prior_question_coverage,
            enable_tools=True,
            reasoning_budget_tokens=preplan_reasoning_budget_tokens(),
            compact_context=True,
            catalog_resolution=scientist_resolution,
        )
        latest = repository.get_interview_session(session_id)
        if latest is None:
            repository.update_preplan_status(
                session_id,
                status="failed",
                error_detail="session disappeared during warmup",
            )
            return
        if any(turn.role == "participant" for turn in latest.turns):
            logger.info(
                "pre-plan skipped because participant turn already exists: session=%s",
                session_id,
            )
            repository.update_preplan_status(session_id, status="late_skipped")
            return
        repository.update_next_plan(session_id, intent)
        repository.update_preplan_status(session_id, status="ready")
        bus.publish_many(
            campaign_id,
            [
                InterviewEvent(
                    name="brain_b_planned",
                    data={
                        "session_id": session_id,
                        "next_plan": intent.model_dump(mode="json"),
                    },
                )
            ],
        )
    except Exception as exc:
        logger.exception(
            "pre-plan background failed: session=%s campaign=%s",
            session_id,
            campaign_id,
        )
        try:
            repository.update_preplan_status(
                session_id,
                status="failed",
                error_detail=str(exc),
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "pre-plan background failed to record terminal failed status: session=%s",
                session_id,
            )


def _last_agent_content_before(
    session: InterviewSessionRecord, pivot_turn_id: str
) -> str:
    """Return the most recent agent content persisted before the pivot turn."""
    last = ""
    for turn in session.turns:
        if turn.id == pivot_turn_id:
            break
        if turn.role == "agent":
            last = turn.content
    return last


async def _stream_closing(
    *,
    router: LiteLLMRouter,
    session: InterviewSessionRecord,
    campaign: Campaign,
    close_reason: str,
    events: list[InterviewEvent],
    repository: InMemoryRepository | None = None,
) -> str:
    """Invoke Brain A in closing mode: no chips, short reflective prose.

    This bypasses ``stream_brain_a`` because that helper assumes a
    ``BrainBIntent`` with chips to render. Closing turns have neither, so
    we issue a dedicated streaming call with a closing-specific system
    message. The text is token-streamed into the event log as ``token``
    events, matching the regular flow. ``repository`` is optional so
    legacy callers without one can still close cleanly via
    ``set_lmstudio_thinking(enabled=False)``; production paths plumb the
    repository so the chatter catalog resolution shapes the request.
    """
    system_prompt = (
        "You are Mira, closing a research conversation. Write 2 to 4 short "
        "sentences grounded in the participant's own signal. No question, "
        "no bullets, no chips. Keep it under 110 words."
    )
    transcript_tail = _transcript_tail(session)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": f"Close reason: {close_reason or 'none'}"},
    ]
    messages.extend(transcript_tail)

    request_payload: dict[str, Any] = {
        "model": "mira-chatter",
        "messages": messages,
        "stream": True,
        "max_tokens": visible_reply_max_tokens(),
        "metadata": {"surface": "interviewer", "brain": "A", "mode": "closing"},
    }
    if repository is not None:
        chatter_resolution = resolve_catalog_route(
            "chatter", repository=repository, campaign=campaign
        )
        apply_reasoning_settings(chatter_resolution, request_payload)
        if chatter_resolution.temperature is not None:
            request_payload["temperature"] = chatter_resolution.temperature
    else:
        set_lmstudio_thinking(request_payload, enabled=False)
    stream = await router.acompletion(**request_payload)
    chunks: list[str] = []
    async for chunk in stream:
        text = _extract_chunk_text(chunk)
        if text:
            chunks.append(text)
            events.append(InterviewEvent(name="token", data={"text": text}))
    return "".join(chunks).strip()


def _extract_chunk_text(chunk: object) -> str:
    choices = chunk.get("choices") if isinstance(chunk, dict) else getattr(chunk, "choices", None)
    if not choices:
        return ""
    first = choices[0]
    delta = first.get("delta") if isinstance(first, dict) else getattr(first, "delta", None)
    if delta is None:
        return ""
    if isinstance(delta, dict):
        return str(delta.get("content") or "")
    return str(getattr(delta, "content", "") or "")


def _last_participant_grounding(
    session: InterviewSessionRecord,
) -> tuple[str, list[str]]:
    """Return ``(last_participant_text, extracted_concept_labels)``.

    Walks turns newest-first for the most recent participant turn. The
    text is the raw message body; the concept labels are extracted from
    that turn's validation snapshot. Both pieces feed the chip grounding
    filter so the orchestrator can drop chips that have zero overlap with
    the participant's own vocabulary.
    """
    for turn in reversed(session.turns):
        if turn.role != "participant":
            continue
        text = (turn.content or "").strip()
        labels: list[str] = []
        validation = turn.validation
        if isinstance(validation, dict):
            for entry in validation.get("extracted_concepts") or []:
                if not isinstance(entry, dict):
                    continue
                label = entry.get("label")
                if isinstance(label, str) and label.strip():
                    labels.append(label.strip())
        return text, labels
    return "", []


def _consecutive_active_axis_history(
    session: InterviewSessionRecord,
) -> tuple[str, int]:
    """Walk back through agent turns and count consecutive same-axis runs.

    Returns ``(prefix, count)`` where ``prefix`` is the leading code (``R1``,
    ``R2``, etc.) of the most recent agent turn's ``active_axis`` and
    ``count`` is the number of consecutive prior agent turns whose
    ``active_axis`` shares that prefix. The orchestrator surfaces both
    values back to Brain B so the planner can rotate before the
    server-side override kicks in. Returns ``("", 0)`` on a cold start or
    when prior agent turns lack a ``brain_b_intent``.
    """
    prefix = ""
    count = 0
    for turn in reversed(session.turns):
        if turn.role != "agent":
            continue
        intent = turn.brain_b_intent
        if intent is None:
            continue
        emitted_prefix = ""
        raw = (intent.active_axis or "").strip()
        for separator in (" ", "—", "-", ":"):
            head = raw.split(separator, 1)[0].strip()
            if head.upper().startswith("R") and head[1:].isdigit():
                emitted_prefix = head.upper()
                break
        if not emitted_prefix:
            head = raw.upper()
            if head.startswith("R") and head[1:].isdigit():
                emitted_prefix = head
        if not emitted_prefix:
            break
        if not prefix:
            prefix = emitted_prefix
            count = 1
            continue
        if emitted_prefix == prefix:
            count += 1
        else:
            break
    return prefix, count


def _last_axes_coverage(session: InterviewSessionRecord) -> list[AxisCoverage]:
    """Return the most recent non-empty ``axes_coverage`` from an agent turn.

    Walks the session's turns newest-first and returns a deep copy so the
    caller can safely pass the list into the next Brain B plan without
    aliasing into repository state. Empty list on cold start.
    """
    for turn in reversed(session.turns):
        if turn.role != "agent":
            continue
        intent = turn.brain_b_intent
        if intent is None:
            continue
        if intent.axes_coverage:
            return [c.model_copy(deep=True) for c in intent.axes_coverage]
    return []


def _last_question_coverage(
    session: InterviewSessionRecord,
) -> list[QuestionCoverage]:
    """Return the most recent ``question_coverage`` from an agent turn.

    Empty list on cold start. The returned objects are deep copies so merge
    enforcement and persistence can compare safely without aliasing repository
    state.
    """
    for turn in reversed(session.turns):
        if turn.role != "agent":
            continue
        intent = turn.brain_b_intent
        if intent is None:
            continue
        if intent.question_coverage:
            return [c.model_copy(deep=True) for c in intent.question_coverage]
    return []


def _role_filtered_outline(
    outline,
    participant_context: dict[str, str],
):
    role_self_description = participant_context.get("role_self_description", "")
    eligible_questions = filter_question_bank_for_role(
        outline.question_bank,
        role_self_description,
    )
    return outline.model_copy(
        update={"question_bank": eligible_questions},
        deep=True,
    )


def _question_coverage_differs(
    prior: QuestionCoverage | None,
    current: QuestionCoverage,
) -> bool:
    if prior is None:
        return current.status != "pending"
    return (
        prior.status != current.status
        or prior.confidence != current.confidence
        or prior.evidence_quote != current.evidence_quote
        or prior.turn_id != current.turn_id
    )


def _attach_question_coverage_turn_ids(
    intent: BrainBIntent,
    *,
    prior_question_coverage: list[QuestionCoverage],
    participant_turn_id: str,
) -> BrainBIntent:
    prior_by_id = {entry.question_id: entry for entry in prior_question_coverage}
    attached: list[QuestionCoverage] = []
    for entry in intent.question_coverage:
        candidate = entry.model_copy(deep=True)
        prior = prior_by_id.get(candidate.question_id)
        if _question_coverage_differs(prior, candidate):
            candidate.turn_id = participant_turn_id
        attached.append(candidate)
    return intent.model_copy(update={"question_coverage": attached})


def _persist_question_answers(
    *,
    repository: InMemoryRepository,
    campaign_id: str,
    session_id: str,
    participant_turn_id: str,
    prior_question_coverage: list[QuestionCoverage],
    intent: BrainBIntent,
) -> None:
    prior_by_id = {entry.question_id: entry for entry in prior_question_coverage}
    for entry in intent.question_coverage:
        if not _question_coverage_differs(prior_by_id.get(entry.question_id), entry):
            continue
        try:
            repository.upsert_question_answer(
                campaign_id=campaign_id,
                session_id=session_id,
                question_id=entry.question_id,
                status=entry.status,
                confidence=entry.confidence,
                evidence_quote=entry.evidence_quote,
                turn_id=participant_turn_id,
            )
        except Exception:
            logger.exception(
                "question_answer persistence failed: session=%s question_id=%s",
                session_id,
                entry.question_id,
            )


def _list_approved_grounding_sources(repository, campaign_id: str) -> list[dict[str, Any]]:
    """Snapshot approved knowledge sources for the Brain-B grounding tool.

    Kept symmetrical with the Designer helper so Brain B sees the same shape
    on either surface.
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


def _transcript_tail(session: InterviewSessionRecord, *, tail: int = 6) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for turn in session.turns[-tail:]:
        role = "assistant" if turn.role == "agent" else "user"
        messages.append({"role": role, "content": turn.content})
    return messages


def _compose_persona(persona_hints: dict[str, str]) -> str:
    if not persona_hints:
        return ""
    ordered = ("name", "role", "tone", "behavior")
    lines: list[str] = []
    for key in ordered:
        value = persona_hints.get(key)
        if value:
            lines.append(f"{key}: {value}")
    for key, value in persona_hints.items():
        if key in ordered or not value:
            continue
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


# ``asyncio`` is imported for side-effect symmetry with callers that spawn
# tasks via ``asyncio.create_task`` over these coroutines. The helper
# functions themselves never schedule anything — the caller is the scheduler.
_ = asyncio  # keep the import from being pruned by zealous formatters.
