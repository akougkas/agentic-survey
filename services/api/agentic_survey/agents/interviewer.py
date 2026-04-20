from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Iterable

from pydantic import ValidationError

from agentic_survey.agents.base import BaseAgent, PromptBundle, load_prompt_text
from agentic_survey.engine.session_policy import SessionSignals
from agentic_survey.llm.client import ChatMessage, LLMClient, LLMUnavailable
from agentic_survey.llm.pool import AgentRole
from agentic_survey.repository import (
    BrainIntentRecord,
    Campaign,
    GetUserInputPayload,
    InterviewSessionRecord,
    InterviewTurnRecord,
    OutlineArtifact,
    ParticipantControl,
    ParticipantFAQEntry,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = load_prompt_text("interviewer_brain_a.md")
SCIENTIST_PROMPT = load_prompt_text("interviewer_brain_b.md")

CLOSING_PROMPT = (
    "You are Mira, closing a completed interview. "
    "Write 2 to 4 short sentences grounded in the participant's own signal. "
    "No question. No bullets. No generic praise. Keep it under 110 words."
)

CONTROL_LABELS: dict[ParticipantControl, str] = {
    "pause": "Pause for now.",
    "skip": "I'd rather skip this.",
    "continue": "Keep going.",
    "stop": "Stop here.",
}

CONTROL_INPUTS: dict[ParticipantControl, set[str]] = {
    "pause": {"pause", "pause for now", "pause here", "lets pause", "let us pause"},
    "skip": {"skip", "skip this", "id rather skip this", "pass on this"},
    "continue": {"continue", "keep going", "lets keep going", "i can keep going"},
    "stop": {"stop", "stop here", "end this", "end here", "i want to stop", "im done"},
}

FAQ_HINTS: dict[str, tuple[str, ...]] = {
    "study-purpose": ("study", "about", "why are you asking", "purpose", "research about"),
    "scientist": ("who is running", "whos running", "scientist", "researcher", "team behind"),
    "sponsor": ("sponsor", "funding", "backed by", "paying for", "company behind"),
    "logistics": ("quoted", "anonymous", "named", "answers", "logistics", "how long", "consent"),
}

ADVICE_PATTERNS = (
    "should i",
    "what should we do",
    "what would you do",
    "what do you recommend",
    "any advice",
    "best practice",
    "whats the right move",
)

CONFUSION_PATTERNS = (
    "what do you mean",
    "not sure what you mean",
    "can you explain",
    "can you say that another way",
    "im confused",
    "i am confused",
)

SENSITIVE_PATTERNS = (
    "panic",
    "anxious",
    "ashamed",
    "embarrass",
    "unsafe",
    "personal",
    "private",
    "fired",
    "laid off",
    "disciplinary",
    "patient",
    "medical",
    "harm",
    "trauma",
    "distress",
)

COMPLETION_PATTERNS = (
    "thats all",
    "nothing else",
    "i think thats it",
    "thats everything",
    "im done",
)

BANNED_PHRASES = (
    "great question",
    "thanks for sharing",
    "thank you for sharing",
    "as an ai",
)


@dataclass(slots=True)
class PlannedInterviewerTurn:
    reply: str
    brain_b_intent: BrainIntentRecord | None = None
    get_user_input: GetUserInputPayload | None = None


def normalize_control_signal(text: str) -> ParticipantControl | None:
    cleaned = _normalize_phrase(text)
    if not cleaned:
        return None
    for control, phrases in CONTROL_INPUTS.items():
        if cleaned in phrases:
            return control
    return None


class Interviewer(BaseAgent):
    name = "interviewer"
    prompt = PromptBundle(
        system=SYSTEM_PROMPT,
        purpose="Conduct adaptive participant interviews with a Brain B handoff.",
    )

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm

    def opening_turn(self, campaign: Campaign) -> PlannedInterviewerTurn:
        topic = campaign.title
        first_probe = (
            campaign.outline.probes[0]
            if campaign.outline.probes
            else "What happened the last time this showed up in your work?"
        )
        reply = (
            f"I'm Mira. I'll keep this conversational and grounded in real work. "
            f"We're here to understand {topic.lower()} through concrete moments, not the polished version. "
            f"If anything feels off, too personal, or not worth getting into, we can skip it, pause, come back later, or stop. "
            f"To start, {first_probe}"
        )
        return PlannedInterviewerTurn(reply=reply)

    async def next_turn(
        self,
        *,
        campaign: Campaign,
        outline: OutlineArtifact,
        session: InterviewSessionRecord,
        session_signals: SessionSignals,
    ) -> PlannedInterviewerTurn:
        if self._llm is None:
            raise LLMUnavailable("interviewer has no llm client configured")
        intent = await self._llm_plan_intent(
            campaign=campaign,
            outline=outline,
            session=session,
            session_signals=session_signals,
        )

        if intent.should_close:
            return PlannedInterviewerTurn(reply="", brain_b_intent=intent)

        reply = await self._llm_reply(
            campaign=campaign,
            outline=outline,
            turns=session.turns,
            session_id=session.id,
            intent=intent,
        )
        return PlannedInterviewerTurn(
            reply=reply,
            brain_b_intent=intent,
            get_user_input=intent.get_user_input,
        )

    async def closing_message(
        self,
        *,
        campaign: Campaign,
        session: InterviewSessionRecord,
        outline: OutlineArtifact,
        close_reason: str = "",
    ) -> str:
        if self._llm is None:
            raise LLMUnavailable("interviewer has no llm client configured")
        return await self._llm_closing_message(
            campaign=campaign,
            session=session,
            outline=outline,
            close_reason=close_reason,
        )

    async def _llm_plan_intent(
        self,
        *,
        campaign: Campaign,
        outline: OutlineArtifact,
        session: InterviewSessionRecord,
        session_signals: SessionSignals,
    ) -> BrainIntentRecord:
        assert self._llm is not None
        faq_entries = _approved_participant_faq(campaign=campaign, outline=outline)
        shared_context = _approved_shared_context(campaign=campaign, outline=outline)
        transcript = "\n".join(f"{turn.role}: {turn.content.strip()}" for turn in session.turns if turn.content.strip())
        faq_text = "\n".join(
            f"- {entry.key}: question={entry.question}; tags={', '.join(entry.tags)}; answer={entry.answer}"
            for entry in faq_entries
        ) or "- none"
        shared_text = "\n".join(f"- {key}: {value}" for key, value in shared_context.items() if value) or "- none"
        objectives = "\n".join(f"- {objective}" for objective in outline.objectives) or "- none"
        probes = "\n".join(f"- {probe}" for probe in outline.probes) or "- none"
        messages = [
            ChatMessage(role="system", content=SCIENTIST_PROMPT),
            ChatMessage(
                role="user",
                content=(
                    f"Campaign: {campaign.title}\n\n"
                    f"Objectives:\n{objectives}\n\n"
                    f"Backstage probes:\n{probes}\n\n"
                    f"Approved FAQ entries:\n{faq_text}\n\n"
                    f"Approved shared context:\n{shared_text}\n\n"
                    f"Session signals:\n"
                    f"- participant_turn_count: {session_signals.participant_turn_count}\n"
                    f"- substantive_turn_count: {session_signals.substantive_turn_count}\n"
                    f"- mean_recent_coverage: {session_signals.mean_recent_coverage:.3f}\n"
                    f"- low_coverage_streak: {session_signals.low_coverage_streak}\n"
                    f"- coverage_complete: {str(session_signals.coverage_complete).lower()}\n"
                    f"- fatigue_signal: {str(session_signals.fatigue_signal).lower()}\n"
                    f"- objective_hits: {json.dumps(session_signals.objective_hits, sort_keys=True)}\n\n"
                    "Transcript:\n"
                    f"{transcript}"
                ),
            ),
        ]
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "interviewer_brain_b_intent",
                "schema": BrainIntentRecord.model_json_schema(),
            },
        }
        raw = await self._llm.chat(
            AgentRole.INTERVIEWER,
            messages,
            campaign=campaign,
            catalog_role="scientist",
            temperature=0.15,
            max_tokens=8192,
            response_format=response_format,
        )
        return self._normalize_intent(
            intent=_parse_brain_intent(raw.content),
            campaign=campaign,
            outline=outline,
            session=session,
            session_signals=session_signals,
        )

    async def _llm_reply(
        self,
        *,
        campaign: Campaign,
        outline: OutlineArtifact,
        turns: list[InterviewTurnRecord],
        session_id: str,
        intent: BrainIntentRecord,
    ) -> str:
        assert self._llm is not None
        faq_lookup = {entry.key: entry for entry in _approved_participant_faq(campaign=campaign, outline=outline)}
        shared_context = _approved_shared_context(campaign=campaign, outline=outline)
        shared_text = "\n".join(
            f"- {key}: {shared_context[key]}"
            for key in intent.shared_context_used
            if key in shared_context and shared_context[key]
        ) or "- none"
        faq_answer = faq_lookup[intent.faq_key].answer if intent.faq_key in faq_lookup else "none"
        controls = (
            ", ".join(CONTROL_LABELS[control] for control in intent.get_user_input.participant_controls)
            if intent.get_user_input is not None and intent.get_user_input.participant_controls
            else "none"
        )
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=SYSTEM_PROMPT),
            ChatMessage(
                role="system",
                content=(
                    f"Turn mode: {intent.response_mode}\n"
                    f"Question intent: {intent.question_intent or 'none'}\n"
                    f"Approved FAQ answer: {faq_answer}\n"
                    f"Approved shared context:\n{shared_text}\n"
                    f"Control options on this turn: {controls}\n"
                    "Keep the reply short. Ask at most one question. "
                    "When the turn mode is faq, answer from the approved FAQ content only and then bridge back only if it feels natural. "
                    "When the turn mode is advice_refusal, decline briefly and return to the participant's own case."
                ),
            ),
        ]
        for turn in turns:
            role = "assistant" if turn.role == "agent" else "user"
            messages.append(ChatMessage(role=role, content=turn.content))

        reply = await self._llm.chat(
            AgentRole.INTERVIEWER,
            messages,
            session_id=session_id,
            campaign=campaign,
            temperature=0.35,
            max_tokens=8192,
            extra_body=_interviewer_request_overrides(
                self._llm,
                campaign=campaign,
                session_id=session_id,
            ),
        )
        if _is_valid_mira_reply(reply.content):
            return reply.content

        repair_messages = list(messages)
        repair_messages.append(
            ChatMessage(
                role="system",
                content=(
                    "Repair your previous draft. Output one short paragraph, under 110 words, with no bullets, no generic praise, and at most one question."
                ),
            )
        )
        repaired = await self._llm.chat(
            AgentRole.INTERVIEWER,
            repair_messages,
            session_id=session_id,
            campaign=campaign,
            temperature=0.2,
            max_tokens=8192,
            extra_body=_interviewer_request_overrides(
                self._llm,
                campaign=campaign,
                session_id=session_id,
            ),
        )
        if _is_valid_mira_reply(repaired.content):
            return repaired.content
        raise LLMUnavailable(f"interviewer produced malformed reply after repair: {repaired.content!r}")

    async def _llm_closing_message(
        self,
        *,
        campaign: Campaign,
        session: InterviewSessionRecord,
        outline: OutlineArtifact,
        close_reason: str,
    ) -> str:
        assert self._llm is not None
        objectives = "\n".join(f"- {objective}" for objective in outline.objectives) or "- none"
        participant_name = session.identity_label.strip() or "the participant"
        messages = [
            ChatMessage(role="system", content=CLOSING_PROMPT),
            ChatMessage(
                role="system",
                content=(
                    f"Participant label: {participant_name}\n"
                    f"Close reason: {close_reason or 'none'}\n"
                    f"Objectives:\n{objectives}\n"
                    "Summarize the participant's signal in their own terms. No praise inflation."
                ),
            ),
        ]
        for turn in session.turns:
            role = "assistant" if turn.role == "agent" else "user"
            messages.append(ChatMessage(role=role, content=turn.content))

        reply = await self._llm.chat(
            AgentRole.INTERVIEWER,
            messages,
            session_id=session.id,
            campaign=campaign,
            temperature=0.2,
            max_tokens=8192,
            extra_body=_interviewer_request_overrides(
                self._llm,
                campaign=campaign,
                session_id=session.id,
            ),
        )
        if _is_valid_closing_message(reply.content):
            return reply.content

        repair_messages = list(messages)
        repair_messages.append(
            ChatMessage(
                role="system",
                content=(
                    "Repair your previous draft. Output 2 to 4 short sentences, no question mark, no bullets, no generic praise, under 110 words."
                ),
            )
        )
        repaired = await self._llm.chat(
            AgentRole.INTERVIEWER,
            repair_messages,
            session_id=session.id,
            campaign=campaign,
            temperature=0.1,
            max_tokens=8192,
            extra_body=_interviewer_request_overrides(
                self._llm,
                campaign=campaign,
                session_id=session.id,
            ),
        )
        if _is_valid_closing_message(repaired.content):
            return repaired.content
        raise LLMUnavailable(f"interviewer produced malformed closing reply after repair: {repaired.content!r}")

    def _normalize_intent(
        self,
        *,
        intent: BrainIntentRecord,
        campaign: Campaign,
        outline: OutlineArtifact,
        session: InterviewSessionRecord,
        session_signals: SessionSignals,
    ) -> BrainIntentRecord:
        faq_lookup = {entry.key: entry for entry in _approved_participant_faq(campaign=campaign, outline=outline)}
        shared_context = _approved_shared_context(campaign=campaign, outline=outline)
        normalized = intent.model_copy(deep=True)
        last_participant = next((turn for turn in reversed(session.turns) if turn.role == "participant"), None)
        last_text = last_participant.content if last_participant is not None else ""
        sensitive_turn = _looks_sensitive(last_text) or (
            normalized.get_user_input.sensitive_turn if normalized.get_user_input is not None else False
        )

        if normalized.faq_key not in faq_lookup:
            normalized.faq_key = None
            if normalized.response_mode == "faq":
                normalized.response_mode = "probe"

        normalized.shared_context_used = [
            key
            for key in normalized.shared_context_used
            if key in shared_context and shared_context[key].strip()
        ]

        if not normalized.question_intent.strip() and normalized.response_mode == "probe":
            normalized.question_intent = _next_probe_intent(outline=outline, session_signals=session_signals)

        if normalized.get_user_input is None:
            normalized.get_user_input = GetUserInputPayload(question="", options=[])

        normalized.get_user_input.options = _clean_chip_options(normalized.get_user_input.options)
        normalized.get_user_input.participant_controls = _clean_controls(normalized.get_user_input.participant_controls)

        if sensitive_turn:
            normalized.get_user_input.sensitive_turn = True
            normalized.get_user_input.participant_controls = ["continue", "skip", "pause", "stop"]
            normalized.get_user_input.suggested_control = "skip"

        if normalized.should_close and not normalized.close_reason:
            normalized.close_reason = _close_reason(
                last_text,
                _control_signal_from_validation(last_participant.validation if last_participant else None),
                session_signals,
            )

        return normalized


def _interviewer_request_overrides(
    llm: LLMClient,
    *,
    campaign: Campaign,
    session_id: str | None = None,
) -> dict:
    if not hasattr(llm, "resolve"):
        return {}
    if session_id is not None:
        endpoint = llm.resolve(AgentRole.INTERVIEWER, session_id=session_id)
    else:
        endpoint = llm.resolve(AgentRole.INTERVIEWER, campaign=campaign)
    model_name = endpoint.model.lower()
    if endpoint.name == "mini" and ("qwen" in model_name or "qwopus" in model_name):
        return {
            "chat_template_kwargs": {"enable_thinking": False},
            "temperature": 0.7,
            "top_p": 0.8,
            "top_k": 20,
            "min_p": 0,
            "repeat_penalty": 1.05,
        }
    return {}


def _approved_shared_context(*, campaign: Campaign, outline: OutlineArtifact) -> dict[str, str]:
    study_context = outline.study_context.strip() or outline.scientist_summary.strip()
    if not study_context:
        primary_objective = outline.objectives[0] if outline.objectives else "how this shows up in real work"
        study_context = (
            f"This study is about {campaign.title}. Mira is trying to understand {primary_objective.rstrip('.').lower()}."
        )
    return {
        "study_context": study_context,
        "market_context": outline.market_context.strip(),
        "technical_context": outline.technical_context.strip(),
        "aggregate_graph_context": outline.aggregate_graph_context.strip()
        or "Any shared study signal stays aggregate and non-identifying.",
    }


def _approved_participant_faq(*, campaign: Campaign, outline: OutlineArtifact) -> list[ParticipantFAQEntry]:
    if outline.participant_faq:
        return [entry.model_copy(deep=True) for entry in outline.participant_faq]
    shared_context = _approved_shared_context(campaign=campaign, outline=outline)
    return [
        ParticipantFAQEntry(
            key="study-purpose",
            question="What is this study about?",
            answer=shared_context["study_context"],
            tags=["study", "purpose", "about", "why"],
        ),
        ParticipantFAQEntry(
            key="scientist",
            question="Who is running this study?",
            answer=(
                "I can share the approved study description, but I do not have a separate scientist bio approved for participants in this session."
            ),
            tags=["scientist", "researcher", "running", "who"],
        ),
        ParticipantFAQEntry(
            key="sponsor",
            question="Who is sponsoring this study?",
            answer="I do not have sponsor details beyond the approved study description for this session.",
            tags=["sponsor", "funding", "company"],
        ),
        ParticipantFAQEntry(
            key="logistics",
            question="What happens with my answers?",
            answer=(
                f"{outline.consent_language.strip()} You can skip, pause, continue later, or stop any time."
            ),
            tags=["consent", "quoted", "anonymous", "named", "answers", "logistics"],
        ),
    ]


def _parse_brain_intent(raw: str) -> BrainIntentRecord:
    try:
        return BrainIntentRecord.model_validate_json(raw)
    except ValidationError:
        pass

    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        raise LLMUnavailable(f"brain-b output was not valid JSON: {raw!r}")
    try:
        return BrainIntentRecord.model_validate_json(match.group(0))
    except ValidationError as exc:
        raise LLMUnavailable(f"brain-b output failed validation: {raw!r}") from exc


def _match_faq_key(text: str, entries: list[ParticipantFAQEntry]) -> str | None:
    lowered = _normalize_phrase(text)
    for entry in entries:
        hints = FAQ_HINTS.get(entry.key, ())
        if any(_normalize_phrase(hint) in lowered for hint in hints):
            return entry.key
        if any(_normalize_phrase(tag) in lowered for tag in entry.tags):
            return entry.key
    return None


def _looks_like_advice_request(text: str) -> bool:
    lowered = _normalize_phrase(text)
    return any(pattern in lowered for pattern in ADVICE_PATTERNS)


def _looks_confused(text: str) -> bool:
    lowered = _normalize_phrase(text)
    return any(pattern in lowered for pattern in CONFUSION_PATTERNS)


def _looks_sensitive(text: str) -> bool:
    lowered = _normalize_phrase(text)
    return any(pattern in lowered for pattern in SENSITIVE_PATTERNS)


def _looks_complete(text: str) -> bool:
    lowered = _normalize_phrase(text)
    return any(pattern in lowered for pattern in COMPLETION_PATTERNS)


def _close_reason(text: str, control_signal: str | None, session_signals: SessionSignals) -> str:
    if control_signal == "stop":
        return "participant_stop"
    if _looks_complete(text):
        return "participant_finished"
    if session_signals.coverage_complete:
        return "coverage_complete"
    if session_signals.fatigue_signal:
        return "fatigue_signal"
    return "brain_b_close"


def _next_probe_intent(*, outline: OutlineArtifact, session_signals: SessionSignals) -> str:
    if outline.probes:
        index = min(session_signals.substantive_turn_count, len(outline.probes) - 1)
        return outline.probes[index]
    return "Ask for one recent concrete example and what check or decision came right after."


def _clean_chip_options(options: list[str]) -> list[str]:
    cleaned: list[str] = []
    for option in options:
        text = " ".join(option.split()).strip()
        if not text or text in cleaned:
            continue
        cleaned.append(text)
    cleaned = cleaned[:4]
    if cleaned and cleaned[-1] != "Discuss this more.":
        if len(cleaned) == 4:
            cleaned[-1] = "Discuss this more."
        else:
            cleaned.append("Discuss this more.")
    return cleaned


def _clean_controls(controls: list[ParticipantControl]) -> list[ParticipantControl]:
    cleaned: list[ParticipantControl] = []
    for control in controls:
        if control not in cleaned:
            cleaned.append(control)
    return cleaned


def _control_signal_from_validation(validation: dict | None) -> str | None:
    if not validation:
        return None
    raw = validation.get("control_signal")
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip().lower()
    return cleaned or None


def _format_question(intent_text: str) -> str:
    text = " ".join(intent_text.split()).strip()
    if not text:
        return "What happened next?"
    text = text.rstrip(".")
    if text.endswith("?"):
        return text
    if text[:1].islower():
        text = text[:1].upper() + text[1:]
    return f"{text}?"


def _conversation_lead(text: str) -> str:
    signal = _first_signal(text)
    if signal:
        return f"I'm hearing the pressure point around {signal}."
    return "Stay with the concrete part for a second."


def _first_signal(text: str) -> str:
    words = [word.strip(".,;:!?\"'") for word in text.split() if len(word) > 4]
    stop = {
        "about",
        "their",
        "there",
        "where",
        "which",
        "would",
        "could",
        "should",
        "because",
        "before",
        "after",
        "still",
        "really",
        "maybe",
        "think",
        "thing",
        "things",
    }
    signals = [word.lower() for word in words if word.lower() not in stop]
    return " and ".join(signals[:2])


def _top_signals(texts: Iterable[str], *, limit: int) -> list[str]:
    counts: dict[str, int] = {}
    order: list[str] = []
    for text in texts:
        for word in re.findall(r"[a-zA-Z][a-zA-Z0-9-]+", text.lower()):
            cleaned = word.strip(".,;:!?\"'")
            if len(cleaned) <= 4:
                continue
            if cleaned in {
                "about",
                "after",
                "again",
                "because",
                "could",
                "first",
                "other",
                "really",
                "should",
                "still",
                "their",
                "there",
                "these",
                "thing",
                "things",
                "think",
                "where",
                "which",
                "while",
                "would",
            }:
                continue
            if cleaned not in counts:
                counts[cleaned] = 0
                order.append(cleaned)
            counts[cleaned] += 1
    ranked = sorted(order, key=lambda item: (-counts[item], order.index(item)))
    return ranked[:limit]


def _human_join(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _normalize_phrase(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]+", "", text.strip().lower())
    return " ".join(cleaned.split())


def _is_valid_mira_reply(text: str) -> bool:
    cleaned = " ".join(text.split())
    if not cleaned or cleaned.startswith(("-", "*")):
        return False
    lowered = cleaned.lower()
    if any(phrase in lowered for phrase in BANNED_PHRASES):
        return False
    if len(cleaned.split()) > 110:
        return False
    if cleaned.count("?") > 1:
        return False
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]
    if len(parts) < 1 or len(parts) > 3:
        return False
    if sum(len(part.split()) for part in parts) < 6:
        return False
    return True


def _is_valid_closing_message(text: str) -> bool:
    cleaned = " ".join(text.split())
    if not cleaned or cleaned.startswith(("-", "*")):
        return False
    lowered = cleaned.lower()
    if any(phrase in lowered for phrase in BANNED_PHRASES):
        return False
    if len(cleaned.split()) > 110:
        return False
    if "?" in cleaned:
        return False
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]
    if len(parts) < 2 or len(parts) > 4:
        return False
    return True
