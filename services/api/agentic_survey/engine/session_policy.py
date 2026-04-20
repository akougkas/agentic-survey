from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
from dataclasses import dataclass, field

from agentic_survey.repository import InterviewSessionRecord, InterviewTurnRecord, OutlineArtifact

_STOP_WORDS = {
    "about",
    "after",
    "again",
    "also",
    "around",
    "because",
    "before",
    "being",
    "between",
    "could",
    "first",
    "from",
    "have",
    "into",
    "just",
    "make",
    "most",
    "only",
    "other",
    "same",
    "should",
    "some",
    "still",
    "than",
    "that",
    "their",
    "there",
    "these",
    "they",
    "this",
    "through",
    "under",
    "very",
    "what",
    "when",
    "where",
    "which",
    "while",
    "with",
    "would",
}


@dataclass(slots=True)
class SessionSignals:
    participant_turn_count: int = 0
    substantive_turn_count: int = 0
    mean_recent_coverage: float = 0.0
    low_coverage_streak: int = 0
    objective_hits: dict[str, int] = field(default_factory=dict)
    coverage_complete: bool = False
    fatigue_signal: bool = False


@dataclass(slots=True)
class _ParticipantSnapshot:
    turn: InterviewTurnRecord
    coverage_score: float
    objective_tags: list[str]
    control_signal: str | None = None


def summarize_session_signals(
    session: InterviewSessionRecord,
    outline: OutlineArtifact,
    validations: Iterable[Mapping[str, object] | dict | None],
) -> SessionSignals:
    participant_turns = [turn for turn in session.turns if turn.role == "participant"]
    participant_turn_count = len(participant_turns)
    validation_list = list(validations)
    if len(validation_list) < participant_turn_count:
        validation_list = [turn.validation for turn in participant_turns]

    snapshots = [
        _participant_snapshot(
            turn=turn,
            outline=outline,
            validation=validation_list[index] if index < len(validation_list) else turn.validation,
        )
        for index, turn in enumerate(participant_turns)
    ]
    substantive = [snapshot for snapshot in snapshots if snapshot.control_signal is None]

    objective_hits = {
        objective: sum(1 for snapshot in substantive if objective in snapshot.objective_tags)
        for objective in outline.objectives
    }
    recent_coverages = [snapshot.coverage_score for snapshot in substantive[-4:]]
    mean_recent_coverage = (
        sum(recent_coverages) / len(recent_coverages) if len(recent_coverages) == 4 else 0.0
    )

    low_coverage_streak = 0
    for snapshot in reversed(substantive):
        if snapshot.coverage_score < 0.25:
            low_coverage_streak += 1
            continue
        break

    coverage_complete = (
        len(recent_coverages) == 4
        and mean_recent_coverage >= 0.75
        and bool(objective_hits)
        and all(hit_count > 0 for hit_count in objective_hits.values())
    )
    fatigue_signal = low_coverage_streak >= 3

    return SessionSignals(
        participant_turn_count=participant_turn_count,
        substantive_turn_count=len(substantive),
        mean_recent_coverage=mean_recent_coverage,
        low_coverage_streak=low_coverage_streak,
        objective_hits=objective_hits,
        coverage_complete=coverage_complete,
        fatigue_signal=fatigue_signal,
    )


def derive_objective_tags(
    *,
    content: str,
    outline: OutlineArtifact,
    validation: Mapping[str, object] | dict | None = None,
) -> list[str]:
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
def _participant_snapshot(
    *,
    turn: InterviewTurnRecord,
    outline: OutlineArtifact,
    validation: Mapping[str, object] | dict | None,
) -> _ParticipantSnapshot:
    control_signal = _control_signal(validation)
    coverage_score = 0.0 if control_signal is not None else _coerce_coverage_score(validation)
    objective_tags = [] if control_signal is not None else derive_objective_tags(
        content=turn.content,
        outline=outline,
        validation=validation,
    )
    return _ParticipantSnapshot(
        turn=turn,
        coverage_score=coverage_score,
        objective_tags=objective_tags,
        control_signal=control_signal,
    )


def _control_signal(validation: Mapping[str, object] | dict | None) -> str | None:
    if validation is None:
        return None
    raw = validation.get("control_signal")
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip().lower()
    return cleaned or None


def _coerce_coverage_score(validation: Mapping[str, object] | dict | None) -> float:
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
            index = int(stripped)
            if 0 <= index < len(outline.objectives):
                matched.append(outline.objectives[index])

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
    unique_items: list[str] = []
    for item in items:
        if item not in unique_items:
            unique_items.append(item)
    return unique_items
