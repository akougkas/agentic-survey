from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from pydantic import BaseModel, Field

from agentic_survey.repository import InterviewSessionRecord, InterviewTurnRecord, OutlineArtifact

__all__ = [
    "SessionSignals",
    "compute_signals",
    "derive_objective_tags",
]


_COVERAGE_HIGH = 0.6
_COVERAGE_LOW = 0.25
_COMPLETION_PATTERNS = (
    "thats all",
    "nothing else",
    "i think thats it",
    "thats everything",
    "im done",
    "i am done",
    "no more",
)

_STOP_WORDS = {
    "about", "after", "again", "also", "around", "because", "before", "being",
    "between", "could", "first", "from", "have", "into", "just", "make", "most",
    "only", "other", "same", "should", "some", "still", "than", "that", "their",
    "there", "these", "they", "this", "through", "under", "very", "what", "when",
    "where", "which", "while", "with", "would",
}


class SessionSignals(BaseModel):
    """Advisory signals about the in-flight interview.

    Signals, not decisions. Close authority lives on
    ``BrainBIntent.should_close`` or scientist override. No helper in this
    module returns a boolean "should_close"; if callers need one they must
    route it through Brain B.
    """

    coverage_streak: int = 0
    low_coverage_streak: int = 0
    objective_hits: list[str] = Field(default_factory=list)
    turn_count: int = 0
    participant_explicit_completion: bool = False


def compute_signals(
    session: InterviewSessionRecord,
    outline: OutlineArtifact,
    validations: Iterable[Mapping[str, object] | dict | None] | None = None,
) -> SessionSignals:
    """Roll up transcript + validator rows into a SessionSignals snapshot."""
    participant_turns = [turn for turn in session.turns if turn.role == "participant"]
    turn_count = len(participant_turns)

    validation_list = list(validations) if validations is not None else []
    if len(validation_list) < turn_count:
        validation_list = [turn.validation for turn in participant_turns]

    coverage_streak = 0
    for index, turn in enumerate(reversed(participant_turns)):
        validation = validation_list[-(index + 1)] if index < len(validation_list) else turn.validation
        if _control_signal(validation) is not None:
            break
        if _coerce_coverage(validation) >= _COVERAGE_HIGH:
            coverage_streak += 1
            continue
        break

    low_coverage_streak = 0
    for index, turn in enumerate(reversed(participant_turns)):
        validation = validation_list[-(index + 1)] if index < len(validation_list) else turn.validation
        if _control_signal(validation) is not None:
            break
        if _coerce_coverage(validation) < _COVERAGE_LOW:
            low_coverage_streak += 1
            continue
        break

    hits: list[str] = []
    for index, turn in enumerate(participant_turns):
        validation = validation_list[index] if index < len(validation_list) else turn.validation
        for tag in derive_objective_tags(
            content=turn.content,
            outline=outline,
            validation=validation,
        ):
            if tag not in hits:
                hits.append(tag)

    participant_explicit_completion = False
    if participant_turns:
        last_text = participant_turns[-1].content.lower()
        participant_explicit_completion = any(
            pattern in last_text for pattern in _COMPLETION_PATTERNS
        )

    return SessionSignals(
        coverage_streak=coverage_streak,
        low_coverage_streak=low_coverage_streak,
        objective_hits=hits,
        turn_count=turn_count,
        participant_explicit_completion=participant_explicit_completion,
    )


def derive_objective_tags(
    *,
    content: str,
    outline: OutlineArtifact,
    validation: Mapping[str, object] | dict | None = None,
) -> list[str]:
    """Map one participant turn onto the outline's objectives.

    Pure function; same stemming + stop-list fallback as the legacy
    version so callers preserve behavior. Prefers explicit
    ``objective_tags`` in ``validation`` when the validator emitted them.
    """
    if not outline.objectives:
        return []
    if _control_signal(validation) is not None:
        return []

    explicit_tags = _explicit_objective_tags(validation, outline)
    if explicit_tags:
        return explicit_tags

    content_tokens = _fingerprint_tokens(content)
    if validation is not None:
        for concept in _concept_labels(validation):
            content_tokens.update(_fingerprint_tokens(concept))

    tags: list[str] = []
    for objective in outline.objectives:
        objective_tokens = _fingerprint_tokens(objective)
        if objective_tokens and _tokens_overlap(objective_tokens, content_tokens):
            tags.append(objective)
    return tags


def _control_signal(validation: Mapping[str, object] | dict | None) -> str | None:
    if validation is None:
        return None
    raw = validation.get("control_signal")
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip().lower()
    return cleaned or None


def _coerce_coverage(validation: Mapping[str, object] | dict | None) -> float:
    if validation is None:
        return 0.0
    raw = validation.get("coverage_score", 0.0)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _explicit_objective_tags(
    validation: Mapping[str, object] | dict | None,
    outline: OutlineArtifact,
) -> list[str]:
    if validation is None:
        return []
    raw_tags = validation.get("objective_tags")
    if not isinstance(raw_tags, list):
        return []

    matched: list[str] = []
    for raw_tag in raw_tags:
        if isinstance(raw_tag, int) and 0 <= raw_tag < len(outline.objectives):
            matched.append(outline.objectives[raw_tag])
            continue
        if not isinstance(raw_tag, str):
            continue
        stripped = raw_tag.strip()
        if stripped in outline.objectives:
            matched.append(stripped)
            continue
        if stripped.isdigit():
            idx = int(stripped)
            if 0 <= idx < len(outline.objectives):
                matched.append(outline.objectives[idx])
    return _unique(matched)


def _concept_labels(validation: Mapping[str, object] | dict) -> list[str]:
    concepts = validation.get("extracted_concepts", [])
    if not isinstance(concepts, list):
        return []
    labels: list[str] = []
    for concept in concepts:
        if isinstance(concept, Mapping):
            label = concept.get("label")
            if isinstance(label, str) and label.strip():
                labels.append(label.strip())
    return labels


def _tokens_overlap(left: set[str], right: set[str]) -> bool:
    for left_token in left:
        for right_token in right:
            if left_token == right_token:
                return True
            if len(left_token) >= 5 and len(right_token) >= 5:
                if left_token.startswith(right_token) or right_token.startswith(left_token):
                    return True
    return False


def _fingerprint_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw in re.findall(r"[a-zA-Z][a-zA-Z0-9-]+", text.lower()):
        token = _stem_token(raw)
        if len(token) < 4 or token in _STOP_WORDS:
            continue
        tokens.add(token)
    return tokens


def _stem_token(token: str) -> str:
    for suffix in ("ing", "tion", "ions", "ment", "ments", "edly", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def _unique(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


_ = InterviewTurnRecord  # re-export module imports (used by type hints in legacy call sites)
