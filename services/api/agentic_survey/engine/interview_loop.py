from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agentic_survey.agents.brain_a import stream_brain_a
from agentic_survey.agents.brain_b_interviewer import (
    InterviewerBrainBError,
    run_brain_b_interviewer,
)
from agentic_survey.agents.validator import Validator
from agentic_survey.domain.intent import BrainBIntent
from agentic_survey.engine.retrieval_cache import RetrievalCache
from agentic_survey.engine.session_policy import (
    SessionSignals,
    compute_signals,
    derive_objective_tags,
)
from agentic_survey.llm.router import LiteLLMRouter
from agentic_survey.repository import (
    Campaign,
    InMemoryRepository,
    InterviewSessionRecord,
    InterviewTurnRecord,
    ParticipantControl,
)
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
]


def opening_turn_message(campaign: Campaign) -> str:
    """The first agent turn at the top of a participant session.

    Kept deterministic (no LLM) so a session boots cleanly even when the
    router is cold; ``run_interview_turn`` takes over from turn 2 onward.
    """
    topic = campaign.title
    first_probe = (
        campaign.outline.probes[0]
        if campaign.outline.probes
        else "What happened the last time this showed up in your work?"
    )
    return (
        f"I'm Mira. I'll keep this conversational and grounded in real work. "
        f"We're here to understand {topic.lower()} through concrete moments, not the polished version. "
        "If anything feels off, too personal, or not worth getting into, we can skip it, pause, come back later, or stop. "
        f"To start, {first_probe}"
    )

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

    ``name`` maps 1:1 to lifecycles.md §2.7 SSE names (``turn_start``,
    ``token``, ``get_user_input``, ``graph_delta``, ``turn_complete``,
    ``session_finished``). ``data`` is the JSON-serializable payload the
    eventual SSE endpoint will emit. Structured only; no per-token
    ``interview_event`` persistence.
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
    """Run a single live interview turn end-to-end.

    Flow:

    1. Persist the participant turn (with validator-or-control-signal
       validation row).
    2. Recompute ``SessionSignals`` (advisory only).
    3. Ask Brain B for a ``BrainBIntent``.
    4. If ``intent.should_close``: stream Brain A's closing prose (no
       chips), persist the agent turn, mark the session finished with
       ``close_reason="brain_b_judgment"``.
    5. Else: stream Brain A's reply tokens, persist the agent turn with
       the ``BrainBIntent`` and its chip set.

    Retrieval cache writes land in step 3 once B2-min wires real retrieval;
    the cache is passed through today so signatures stabilize.
    """
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
        last_agent = next(
            (turn.content for turn in reversed(session.turns) if turn.role == "agent"),
            "",
        )
        result = await validator.validate(
            campaign=campaign,
            content=content,
            outline=campaign.outline,
            previous_agent_question=last_agent,
        )
        validation_payload = result.to_dict()
        validation_payload["objective_tags"] = derive_objective_tags(
            content=content,
            outline=campaign.outline,
            validation=validation_payload,
        )
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
        events.append(InterviewEvent(name="session_paused", data={"session_id": paused.id, "reason": "participant_paused"}))
        return InterviewTurnResult(
            session=paused,
            participant_turn=participant_turn,
            events=events,
        )

    refreshed = repository.get_interview_session(session.id)
    assert refreshed is not None

    participant_validations = [turn.validation for turn in refreshed.turns if turn.role == "participant"]
    signals = compute_signals(refreshed, campaign.outline, participant_validations)

    if control == "stop":
        close_reason = "participant_stop"
        reply_text = await _stream_closing(
            router=router,
            session=refreshed,
            campaign=campaign,
            close_reason=close_reason,
            events=events,
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
                "turn_count": signals.turn_count,
                "coverage_streak": signals.coverage_streak,
                "low_coverage_streak": signals.low_coverage_streak,
                "objective_hits": signals.objective_hits,
            },
        )
        finished = repository.finish_interview_session(refreshed.id, close_reason=close_reason)
        events.append(InterviewEvent(name="turn_complete", data={"turn_id": agent_turn.id}))
        events.append(InterviewEvent(name="session_finished", data={"session_id": finished.id, "close_reason": close_reason}))
        return InterviewTurnResult(
            session=finished,
            agent_turn=agent_turn,
            participant_turn=participant_turn,
            signals=signals,
            close_reason=close_reason,
            events=events,
        )

    transcript_tail = _transcript_tail(refreshed)

    base_search = build_search_knowledge(
        repository=repository,
        campaign_id=campaign.id,
        surface="interviewer",
    )

    async def _cached_search(query: str, k: int) -> list[dict[str, Any]]:
        cached = cache.get(refreshed.id, query)
        if cached:
            # Serve from cache; real chunk bodies are rehydrated by callers via repository.
            return [
                {"chunk_id": chunk_id, "score": score, "cached": True}
                for entry in cached
                for chunk_id, score in zip(entry.chunk_ids, entry.scores)
            ][:k]
        results = await base_search(query, k)
        chunk_ids = [hit.get("chunk_id", "") for hit in results if isinstance(hit, dict)]
        scores = [float(hit.get("score", 0.0)) for hit in results if isinstance(hit, dict)]
        if chunk_ids:
            cache.put(refreshed.id, query, chunk_ids, scores)
        return results

    intent = await run_brain_b_interviewer(
        outline=campaign.outline,
        transcript_tail=transcript_tail,
        session_signals=signals,
        router=router,
        search_knowledge=_cached_search,
    )

    if intent.should_close:
        close_reason = "brain_b_judgment"
        reply_text = await _stream_closing(
            router=router,
            session=refreshed,
            campaign=campaign,
            close_reason=close_reason,
            events=events,
        )
        agent_turn = repository.append_interview_turn(
            refreshed.id,
            role="agent",
            content=reply_text,
            brain_b_intent=intent,
            get_user_input=intent.get_user_input,
            validation={
                "closing": True,
                "close_reason": close_reason,
                "turn_count": signals.turn_count,
                "coverage_streak": signals.coverage_streak,
                "low_coverage_streak": signals.low_coverage_streak,
                "objective_hits": signals.objective_hits,
            },
        )
        finished = repository.finish_interview_session(refreshed.id, close_reason=close_reason)
        events.append(InterviewEvent(name="turn_complete", data={"turn_id": agent_turn.id}))
        events.append(InterviewEvent(name="session_finished", data={"session_id": finished.id, "close_reason": close_reason}))
        return InterviewTurnResult(
            session=finished,
            agent_turn=agent_turn,
            participant_turn=participant_turn,
            brain_b_intent=intent,
            signals=signals,
            close_reason=close_reason,
            events=events,
        )

    persona = _compose_persona(campaign.outline.persona_hints)
    chunks: list[str] = []
    async for token in stream_brain_a(
        role="mira-chatter",
        prompt_md_path=INTERVIEWER_BRAIN_A_PROMPT,
        transcript_tail=transcript_tail,
        brain_b_intent=intent,
        persona=persona,
        router=router,
    ):
        chunks.append(token)
        events.append(InterviewEvent(name="token", data={"text": token}))

    reply_text = "".join(chunks).strip()

    agent_turn = repository.append_interview_turn(
        refreshed.id,
        role="agent",
        content=reply_text,
        brain_b_intent=intent,
        get_user_input=intent.get_user_input,
    )
    events.append(
        InterviewEvent(
            name="get_user_input",
            data={
                "turn_id": agent_turn.id,
                "question": intent.get_user_input.question,
                "options": list(intent.get_user_input.options),
                "allow_free_text": intent.get_user_input.allow_free_text,
            },
        )
    )
    events.append(InterviewEvent(name="turn_complete", data={"turn_id": agent_turn.id}))

    updated_session = repository.get_interview_session(refreshed.id)
    assert updated_session is not None
    return InterviewTurnResult(
        session=updated_session,
        agent_turn=agent_turn,
        participant_turn=participant_turn,
        brain_b_intent=intent,
        signals=signals,
        events=events,
    )


async def _stream_closing(
    *,
    router: LiteLLMRouter,
    session: InterviewSessionRecord,
    campaign: Campaign,
    close_reason: str,
    events: list[InterviewEvent],
) -> str:
    """Invoke Brain A in closing mode: no chips, short reflective prose.

    This bypasses ``stream_brain_a`` because that helper assumes a
    ``BrainBIntent`` with chips to render. Closing turns have neither, so
    we issue a dedicated streaming call with a closing-specific system
    message. The text is token-streamed into the event log as ``token``
    events, matching the regular flow.
    """
    system_prompt = (
        "You are Mira, closing a completed interview. Write 2 to 4 short "
        "sentences grounded in the participant's own signal. No question, "
        "no bullets, no chips. Keep it under 110 words."
    )
    transcript_tail = _transcript_tail(session)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": f"Close reason: {close_reason or 'none'}"},
    ]
    messages.extend(transcript_tail)

    stream = await router.acompletion(
        model="mira-chatter",
        messages=messages,
        stream=True,
        metadata={"surface": "interviewer", "brain": "A", "mode": "closing"},
    )
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


