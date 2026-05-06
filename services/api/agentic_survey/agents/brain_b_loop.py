from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from agentic_survey.agents.tools.registry import ToolDispatchError, ToolRegistry
from agentic_survey.domain.intent import AxisCoverage, BrainBIntent, QuestionCoverage
from agentic_survey.llm.reasoning import (
    repair_completion_tokens,
    reasoning_completion_tokens,
    sanitize_thinking_messages,
    set_lmstudio_thinking,
)

__all__ = [
    "BrainBLoopError",
    "BrainBLoopResult",
    "BrainBToolBudgetExceeded",
    "ToolCallRecord",
    "_apply_closing_prose_guard",
    "_floor_active_axis",
    "_force_axis_rotation",
    "_merge_question_coverage",
    "_question_intent_is_axis_label",
    "run_brain_b_with_tools",
]

logger = logging.getLogger(__name__)

Surface = Literal["designer", "interviewer"]
_PROMPTS_DIR = Path(__file__).with_name("prompts")
_DISCUSS_MORE = "Discuss this more."
_EMIT_INTENT_TOOL_NAME = "emit_brain_b_intent"
_RESULT_LOG_LIMIT = 240
_REPAIR_CONTEXT_LIMIT = 6000
_REPAIR_TRANSCRIPT_TURNS = 8


class BrainBLoopError(RuntimeError):
    """Raised when the tool-calling loop cannot produce a valid BrainBIntent."""

    def __init__(
        self,
        message: str,
        *,
        raw_output: str = "",
        surface: Surface = "designer",
    ) -> None:
        super().__init__(message)
        self.raw_output = raw_output
        self.surface = surface


class BrainBToolBudgetExceeded(BrainBLoopError):
    """Raised when Brain B issues more tool calls than ``max_tool_calls`` permits."""


@dataclass(slots=True)
class ToolCallRecord:
    """One observed tool invocation during the loop.

    ``result`` is the unclipped handler return value so downstream audit has
    full fidelity. ``result_summary`` is a truncated display form for logs.
    """

    name: str
    arguments: dict[str, Any]
    result: Any
    result_summary: str


@dataclass(slots=True)
class BrainBLoopResult:
    intent: BrainBIntent
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    raw_output: str = ""


@dataclass(slots=True)
class _QuestionCoverageMergeStats:
    emitted_count: int = 0
    dropped_out_of_bank: int = 0
    regressions_overridden: int = 0
    final_count: int = 0


def _brain_b_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "brain_b_intent",
            "schema": _strip_json_schema_annotations(
                BrainBIntent.model_json_schema()
            ),
        },
    }


def _strip_json_schema_annotations(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_json_schema_annotations(item)
            for key, item in value.items()
            if key not in {"default", "title"}
        }
    if isinstance(value, list):
        return [_strip_json_schema_annotations(item) for item in value]
    return value


def _brain_b_output_tool_schema() -> dict[str, Any]:
    """Function-call schema for Brain B's final structured handoff.

    LM Studio handles flat OpenAI tool schemas more reliably than
    response_format schemas with nested ``$defs``. The schema is intentionally
    explicit and mostly required so the model sees the exact field names it
    must emit. Pydantic remains the source of truth after the call.
    """
    return {
        "type": "function",
        "function": {
            "name": _EMIT_INTENT_TOOL_NAME,
            "description": (
                "Emit the final BrainBIntent object as function arguments. "
                "Use score for axes_coverage entries. get_user_input must be "
                "an object. The last get_user_input option must be exactly "
                "Discuss this more."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "active_axis": {"type": "string"},
                    "axes_coverage": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "axis": {"type": "string"},
                                "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                                "gap": {"type": "string"},
                            },
                            "required": ["axis", "score", "gap"],
                        },
                    },
                    "question_coverage": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "question_id": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": [
                                        "pending",
                                        "targeting",
                                        "partial",
                                        "satisfied",
                                        "skipped",
                                    ],
                                },
                                "confidence": {
                                    "type": "number",
                                    "minimum": 0.0,
                                    "maximum": 1.0,
                                },
                                "evidence_quote": {"type": "string"},
                                "turn_id": {"type": "string"},
                            },
                            "required": [
                                "question_id",
                                "status",
                                "confidence",
                                "evidence_quote",
                                "turn_id",
                            ],
                        },
                    },
                    "question_intent": {"type": "string"},
                    "get_user_input": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "options": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 2,
                                "maxItems": 5,
                            },
                            "allow_free_text": {"type": "boolean"},
                        },
                        "required": ["question", "options", "allow_free_text"],
                    },
                    "outline_patch": {
                        "type": "object",
                        "properties": {
                            "sections": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "section": {"type": "string"},
                                        "op": {
                                            "type": "string",
                                            "enum": ["replace", "append", "remove"],
                                        },
                                        "value": {},
                                    },
                                    "required": ["section", "op"],
                                },
                            },
                            "provenance": {"type": "string"},
                            "summary": {"type": "string"},
                        },
                        "required": ["sections", "provenance", "summary"],
                    },
                    "ready_for_review": {"type": "boolean"},
                    "should_close": {"type": "boolean"},
                    "closing": {"type": "boolean"},
                    "retrieval_used": {"type": "boolean"},
                    "retrieval_chunks": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "active_axis",
                    "axes_coverage",
                    "question_coverage",
                    "question_intent",
                    "get_user_input",
                    "ready_for_review",
                    "should_close",
                    "closing",
                    "retrieval_used",
                    "retrieval_chunks",
                ],
            },
        },
    }


def _forced_output_tool_choice() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": _EMIT_INTENT_TOOL_NAME},
    }


_OPTION_MAX_LEN = 120
_OPTION_TOTAL_CAP = 4
_OPTION_REJECT_SUBSTRINGS: tuple[str, ...] = (
    # Schema-rule fragments small models occasionally lift verbatim from
    # the system prompt instead of synthesizing a real chip.
    "options_are_3_or_4_strings",
    "discuss_this_more",
    "must contain 3 or 4 strings",
    "the last string must be literally",
    "[noun]",
)


def _sanitize_option(raw: str) -> str:
    """Normalize a single chip option string for participant display.

    Strips whitespace, drops surrounding square brackets ("[Skip this]"
    is a documented prompt foible), collapses repeated whitespace, and
    truncates to ``_OPTION_MAX_LEN`` so a paragraph-quote of the
    participant's prior message can never reach the UI as a chip.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    if text.startswith("[") and text.endswith("]") and len(text) > 2:
        text = text[1:-1].strip()
    text = " ".join(text.split())
    if len(text) > _OPTION_MAX_LEN:
        text = text[: _OPTION_MAX_LEN - 1].rstrip() + "…"
    return text


_GROUNDING_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_./-]{2,}")
_GROUNDING_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "into",
        "your",
        "their",
        "would",
        "could",
        "about",
        "what",
        "when",
        "where",
        "which",
        "those",
        "these",
        "have",
        "been",
        "being",
        "more",
        "than",
        "that",
        "this",
        "very",
        "some",
        "most",
        "just",
        "much",
        "also",
        "still",
        "every",
        "after",
        "before",
        "during",
        "while",
        "because",
        "though",
        "without",
        "within",
        "across",
        "through",
        "around",
        "between",
        "discuss",
    }
)


def _grounding_corpus(
    last_participant_message: str,
    participant_extracted_concepts: list[str] | None,
) -> set[str]:
    """Build the case-insensitive token / phrase corpus a chip must overlap.

    Concept labels enter whole-phrase (lowercased, stripped) so multi-word
    concepts like ``Lustre filesystem`` match a chip that contains the same
    phrase. Tokens from the participant's last message enter individually,
    skipping a small stopword set so common conjunctions do not falsely
    ground a generic chip. An empty corpus disables the filter so a cold
    start does not strip the model's only chips.
    """
    corpus: set[str] = set()
    for label in participant_extracted_concepts or []:
        if not isinstance(label, str):
            continue
        cleaned = label.strip().lower()
        if cleaned:
            corpus.add(cleaned)
    if last_participant_message:
        for match in _GROUNDING_TOKEN_RE.finditer(last_participant_message):
            token = match.group(0).strip(".,;:!?\"'()[]").lower()
            if not token or len(token) < 4:
                continue
            if token in _GROUNDING_STOPWORDS:
                continue
            corpus.add(token)
    return corpus


def _chip_is_grounded(chip: str, corpus: set[str]) -> bool:
    if not corpus:
        return True
    text = chip.lower()
    for token in corpus:
        if not token:
            continue
        if " " in token or "/" in token or "-" in token or "_" in token:
            if token in text:
                return True
            continue
        if re.search(rf"\b{re.escape(token)}\b", text):
            return True
    return False


def _normalize_discuss_more(
    raw: str,
    *,
    last_participant_message: str = "",
    participant_extracted_concepts: list[str] | None = None,
) -> str:
    """Force ``get_user_input.options`` to a clean chip set ending with
    'Discuss this more.'.

    Local models sometimes skip the verbatim contract, parrot the prompt's
    schema rules, paragraph-quote the participant's prior message, or emit
    duplicate options. The normalizer:

    - Drops empty and ``Discuss this more.``-equivalent entries.
    - Strips bracket-wrapping (``"[Skip this]"`` is a known prompt foible)
      and caps each chip at ``_OPTION_MAX_LEN`` so paragraph-quotes
      cannot reach the UI.
    - Drops chips whose text matches a known schema-rule fragment so
      prompt leakage like ``options_are_3_or_4_strings…`` never displays.
    - Drops chips that fail the grounding check: zero overlap with the
      participant's last message AND zero overlap with the validator's
      extracted concept labels for that turn. An empty corpus (cold start)
      passes everything through.
    - Deduplicates case-insensitively while preserving first occurrence.
    - Caps the total to ``_OPTION_TOTAL_CAP`` (3 anchors + the canonical
      "Discuss this more." closing).

    If the payload is not parseable JSON the text flows through unchanged
    so the caller's ValidationError diagnostics stay intact.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    gui = payload.get("get_user_input")
    if not isinstance(gui, dict):
        return raw
    options = gui.get("options")
    if not isinstance(options, list) or not options:
        return raw
    grounding_corpus = _grounding_corpus(
        last_participant_message,
        participant_extracted_concepts,
    )
    cleaned: list[str] = []
    fallback: list[str] = []
    seen: set[str] = set()
    dropped_ungrounded = 0
    for opt in options:
        text = _sanitize_option(str(opt))
        if not text:
            continue
        lowered = text.lower()
        if lowered == _DISCUSS_MORE.lower():
            continue
        if any(marker in lowered for marker in _OPTION_REJECT_SUBSTRINGS):
            continue
        if lowered in seen:
            continue
        if not _chip_is_grounded(text, grounding_corpus):
            dropped_ungrounded += 1
            if len(fallback) < _OPTION_TOTAL_CAP - 1:
                fallback.append(text)
            continue
        seen.add(lowered)
        cleaned.append(text)
        if len(cleaned) >= _OPTION_TOTAL_CAP - 1:
            break
    if dropped_ungrounded:
        logger.warning(
            "brain_b chip grounding filter dropped chips count=%s remaining=%s",
            dropped_ungrounded,
            len(cleaned),
        )
    if not cleaned and fallback:
        # Filter killed every chip. Schema demands min 2 options; keeping the
        # least-bad ungrounded chip as a single anchor lets the turn reach
        # the participant. The next turn's planner sees the filter warning.
        cleaned.append(fallback[0])
        logger.warning(
            "brain_b chip grounding filter saved one ungrounded chip surface=fallback",
        )
    cleaned.append(_DISCUSS_MORE)
    gui["options"] = cleaned
    payload["get_user_input"] = gui
    return json.dumps(payload)


def _prompt_path(surface: Surface) -> Path:
    return _PROMPTS_DIR / f"{surface}_brain_b.md"


def _extract_message(response: object) -> dict[str, Any]:
    choices = response.get("choices") if isinstance(response, dict) else getattr(response, "choices", None)
    if not choices:
        return {}
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else getattr(first, "message", None)
    if message is None:
        return {}
    if isinstance(message, dict):
        return message
    content = getattr(message, "content", "")
    reasoning_content = getattr(message, "reasoning_content", "")
    tool_calls = getattr(message, "tool_calls", None)
    return {
        "content": content,
        "reasoning_content": reasoning_content,
        "tool_calls": tool_calls,
    }


def _message_content(message: dict[str, Any]) -> str:
    content = str(message.get("content") or "").strip()
    if content:
        return content
    reasoning_content = str(message.get("reasoning_content") or "").strip()
    if _looks_like_json_object(reasoning_content):
        return reasoning_content
    return ""


def _looks_like_json_object(raw: str) -> bool:
    stripped = raw.strip()
    return stripped.startswith("{") and stripped.endswith("}")


def _normalize_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    tool_calls = message.get("tool_calls")
    if not tool_calls:
        return []
    normalized: list[dict[str, Any]] = []
    for call in tool_calls:
        if isinstance(call, dict):
            normalized.append(call)
            continue
        function = getattr(call, "function", None)
        normalized.append(
            {
                "id": getattr(call, "id", ""),
                "type": getattr(call, "type", "function"),
                "function": {
                    "name": getattr(function, "name", "") if function is not None else "",
                    "arguments": getattr(function, "arguments", "") if function is not None else "",
                },
            }
        )
    return normalized


def _tool_call_name(call: dict[str, Any]) -> str:
    function = call.get("function") or {}
    return str(function.get("name") or "")


def _tool_call_arguments(call: dict[str, Any]) -> str:
    function = call.get("function") or {}
    arguments = function.get("arguments")
    if isinstance(arguments, str):
        return arguments
    if arguments is None:
        return "{}"
    try:
        return json.dumps(arguments, default=str)
    except (TypeError, ValueError):
        return str(arguments)


def _summarize(value: Any) -> str:
    try:
        rendered = json.dumps(value, default=str)
    except (TypeError, ValueError):
        rendered = str(value)
    if len(rendered) <= _RESULT_LOG_LIMIT:
        return rendered
    return rendered[:_RESULT_LOG_LIMIT] + "…"


def _clip_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _compact_brain_b_repair_messages(
    *,
    system_context: list[str],
    transcript_tail: list[dict[str, Any]],
    tool_calls_made: list[ToolCallRecord],
    validation_error: Exception,
) -> list[dict[str, str]]:
    context_parts: list[str] = []
    for item in system_context:
        if not item:
            continue
        context_parts.append(_clip_text(item, 1400))
        if len("\n\n".join(context_parts)) >= _REPAIR_CONTEXT_LIMIT:
            break
    tool_payload = [
        {
            "name": call.name,
            "arguments": call.arguments,
            "result_summary": call.result_summary,
        }
        for call in tool_calls_made
    ]
    user_payload = {
        "validation_error": str(validation_error),
        "context": _clip_text("\n\n".join(context_parts), _REPAIR_CONTEXT_LIMIT),
        "transcript_tail": transcript_tail[-_REPAIR_TRANSCRIPT_TURNS:],
        "observed_tool_calls": tool_payload,
    }
    return [
        {
            "role": "system",
            "content": (
                "You are Mira's Brain B planner. Return only one valid BrainBIntent "
                "JSON object. No markdown. No prose outside JSON. No reasoning text. "
                "Use axis prefixes from the outline when available. Scores are "
                "fractions from 0.0 to 1.0. get_user_input.options must end with "
                "Discuss this more."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(user_payload, default=str),
        },
    ]


def _observed_search_queries(tool_calls: list[ToolCallRecord]) -> list[str]:
    """Pull the ``query`` arg from every observed ``search_knowledge`` call.

    The audit drawer needs this to show the operator what Mira actually
    asked the knowledge base, since the BrainBIntent model itself does
    not carry tool-call history.
    """
    queries: list[str] = []
    for call in tool_calls:
        if call.name != "search_knowledge":
            continue
        if not isinstance(call.arguments, dict):
            continue
        query = call.arguments.get("query")
        if isinstance(query, str) and query.strip():
            queries.append(query.strip())
    return queries


def _log_brain_b_summary(
    *,
    surface: Surface,
    iterations: int,
    tool_calls: list[ToolCallRecord],
    intent: BrainBIntent,
    parse_retries: int,
) -> None:
    """Emit one structured audit line per Brain B turn.

    Live ops needs to see Brain B activity in the API log alongside the
    ``llm_call_audit`` lines from the validator path. The validator path
    goes through ``LLMClient._acompletion`` which fires success_callback
    manually; ``brain_b_loop`` calls ``router.acompletion`` directly so
    no audit row appears in the log otherwise.

    This summary captures the load-bearing fields: tool-call count, the
    actual retrieval queries, axes-coverage spread, question-coverage
    totals, should_close, and parse retries. Logged at WARNING so it
    shows in the same default uvicorn output as the existing
    llm_call_audit lines.
    """
    search_queries = _observed_search_queries(tool_calls)
    tool_names = sorted({call.name for call in tool_calls})
    axes_scores = [coverage.score for coverage in intent.axes_coverage]
    axes_max = max(axes_scores) if axes_scores else 0.0
    axes_zero_count = sum(1 for score in axes_scores if score <= 0.0)
    payload = {
        "surface": surface,
        "iterations": iterations,
        "parse_retries": parse_retries,
        "tool_calls_count": len(tool_calls),
        "tool_names": tool_names,
        "search_queries": search_queries,
        "retrieval_used": bool(intent.retrieval_used),
        "retrieval_chunks_count": len(intent.retrieval_chunks),
        "axes_count": len(axes_scores),
        "axes_max": axes_max,
        "axes_zero_count": axes_zero_count,
        "question_coverage_count": len(intent.question_coverage),
        "should_close": bool(intent.should_close),
    }
    logger.warning("brain_b_summary %s", json.dumps(payload, sort_keys=True, default=str))
    if (
        intent.retrieval_used
        and axes_scores
        and axes_zero_count == len(axes_scores)
    ):
        # Substantive turn: retrieval fired and the model emitted a full
        # axes_coverage payload, but every score is zero. The orchestrator's
        # monotonic backstop accepts that (zero is monotonic vs zero), but
        # operators need a visible signal that the model is no longer
        # scoring the rubric.
        logger.warning(
            "brain_b axes_coverage stayed all-zero on substantive turn surface=%s",
            surface,
        )


def _finish_reason(response: object) -> str:
    choices = response.get("choices") if isinstance(response, dict) else getattr(response, "choices", None)
    if not choices:
        return ""
    first = choices[0]
    value = first.get("finish_reason") if isinstance(first, dict) else getattr(first, "finish_reason", "")
    return str(value or "")


def _log_brain_b_llm_result(
    *,
    surface: Surface,
    iteration: int,
    terminal_only: bool,
    thinking_enabled: bool,
    has_tools: bool,
    has_response_format: bool,
    elapsed_ms: int,
    response: object,
    message: dict[str, Any],
    tool_calls: list[dict[str, Any]],
) -> None:
    content = str(message.get("content") or "")
    reasoning_content = str(message.get("reasoning_content") or "")
    payload = {
        "surface": surface,
        "iteration": iteration,
        "terminal_only": terminal_only,
        "thinking_enabled": thinking_enabled,
        "has_tools": has_tools,
        "has_response_format": has_response_format,
        "elapsed_ms": elapsed_ms,
        "finish_reason": _finish_reason(response),
        "content_chars": len(content.strip()),
        "reasoning_chars": len(reasoning_content.strip()),
        "tool_call_count": len(tool_calls),
    }
    logger.warning("brain_b_llm_result %s", json.dumps(payload, sort_keys=True, default=str))


def _observed_retrieval_chunks(tool_calls: list[ToolCallRecord]) -> list[str]:
    chunk_ids: list[str] = []
    for call in tool_calls:
        if call.name != "search_knowledge":
            continue
        if not isinstance(call.result, list):
            continue
        for hit in call.result:
            if not isinstance(hit, dict):
                continue
            chunk_id = hit.get("chunk_id")
            if chunk_id:
                chunk_ids.append(str(chunk_id))
    return chunk_ids


_AXIS_PREFIX_RE = re.compile(r"^(R\d+)", re.IGNORECASE)
_AXIS_TOKEN_RE = re.compile(r"\bR\d+\b", re.IGNORECASE)


def _axis_prefix(axis: str) -> str:
    stripped = (axis or "").strip()
    match = _AXIS_PREFIX_RE.match(stripped)
    if match:
        return match.group(1).upper()
    return stripped


def _axis_token(text: str) -> str:
    match = _AXIS_TOKEN_RE.search((text or "").strip())
    if match:
        return match.group(0).upper()
    return ""


def _clamp_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


def _normalize_axes_coverage(
    intent: BrainBIntent,
    *,
    rubric_axes: list[str],
    prior_axes: list[AxisCoverage] | None,
) -> BrainBIntent:
    prior_score_by_prefix: dict[str, float] = {}
    prior_gap_by_prefix: dict[str, str] = {}
    for entry in prior_axes or []:
        prefix = _axis_prefix(entry.axis)
        if not prefix:
            continue
        prior_score_by_prefix[prefix] = _clamp_score(entry.score)
        prior_gap_by_prefix[prefix] = entry.gap or ""

    emitted_score_by_prefix: dict[str, float] = {}
    emitted_gap_by_prefix: dict[str, str] = {}
    for entry in intent.axes_coverage:
        prefix = _axis_prefix(entry.axis)
        if not prefix:
            continue
        emitted_score_by_prefix[prefix] = _clamp_score(entry.score)
        emitted_gap_by_prefix[prefix] = entry.gap or ""

    normalized: list[AxisCoverage] = []
    axis_by_prefix: dict[str, str] = {}
    for raw_axis in rubric_axes:
        prefix = _axis_prefix(raw_axis)
        axis_by_prefix[prefix] = raw_axis
        prior_score = prior_score_by_prefix.get(prefix, 0.0)
        if prefix in emitted_score_by_prefix:
            final_score = max(prior_score, emitted_score_by_prefix[prefix])
            gap = emitted_gap_by_prefix.get(prefix, "") or prior_gap_by_prefix.get(prefix, "")
        else:
            final_score = prior_score
            gap = prior_gap_by_prefix.get(prefix, "")
        normalized.append(AxisCoverage(axis=prefix, score=final_score, gap=gap))
    active_axis = intent.active_axis.strip()
    active_prefix = _axis_prefix(active_axis)
    if active_prefix not in axis_by_prefix:
        active_prefix = _axis_token(intent.question_intent)
    if active_prefix in axis_by_prefix:
        active_axis = axis_by_prefix[active_prefix]

    question_intent = intent.question_intent.strip()
    if intent.get_user_input.question.strip() and _question_intent_is_axis_label(
        question_intent,
        active_prefix=active_prefix,
        rubric_axes=rubric_axes,
    ):
        prefix_lead = f"{active_prefix}: " if active_prefix else ""
        question_intent = prefix_lead + intent.get_user_input.question.strip()

    return intent.model_copy(
        update={
            "active_axis": active_axis,
            "axes_coverage": normalized,
            "question_intent": question_intent,
        }
    )


def _question_intent_is_axis_label(
    question_intent: str,
    *,
    active_prefix: str,
    rubric_axes: list[str],
) -> bool:
    """Return True when ``question_intent`` is a rubric label, not an operational sentence.

    Brain B sometimes emits a study-level descriptor (the bare axis prefix
    ``R1``, the axis heading ``R1 — Lifecycle pain topology``, or the full
    rubric axis label) instead of a turn-level intent that names what answer
    the probe is trying to elicit. The orchestrator detects those shapes and
    reforms the field from ``get_user_input.question`` so downstream audit
    and analyst rollups carry a real operational intent.

    A normal operational intent like ``R1: Where in your last cryo-EM run did
    staging cost the most time?`` is left untouched because it is neither the
    bare prefix nor a prefix-equality match against any rubric label segment.
    """
    qi = question_intent.strip()
    if not qi:
        return False
    qi_upper = qi.upper()
    if active_prefix and qi_upper == active_prefix.upper():
        return True
    for raw_axis in rubric_axes:
        axis_norm = (raw_axis or "").strip().upper()
        if not axis_norm:
            continue
        if qi_upper == axis_norm:
            return True
        for separator in (":", "—", "-"):
            head = axis_norm.split(separator, 1)[0].strip()
            if head and qi_upper == head:
                return True
    return False


_ACTIVE_AXIS_FLOOR = 0.20


def _floor_active_axis(
    intent: BrainBIntent,
    *,
    rubric_axes: list[str],
    floor: float = _ACTIVE_AXIS_FLOOR,
) -> BrainBIntent:
    """Bump the active axis to a minimum floor when a substantive turn left it at zero.

    Some local backends (notably Nemotron OMNI) emit ``axes_coverage`` as
    all-zeros even on substantive turns. The monotonic backstop in
    ``_normalize_axes_coverage`` accepts zero-vs-zero, which leaves the
    operator console showing flat rubric coverage despite real evidence in
    the transcript. This floor catches that case: when the turn is
    substantive (retrieval fired or Brain B advanced any question's status
    to ``partial`` or ``satisfied``) AND the active axis is in the rubric
    AND its current score is below ``floor``, raise it to ``floor``.

    Brain B's own positive emissions are preserved untouched. Non-substantive
    turns are left alone so the floor does not wash out a genuinely empty
    response.
    """
    if not _is_substantive_turn(intent):
        return intent
    active_prefix = _axis_prefix(intent.active_axis)
    if not active_prefix:
        return intent
    rubric_prefixes = {_axis_prefix(axis) for axis in rubric_axes if axis}
    if active_prefix not in rubric_prefixes:
        return intent
    new_axes: list[AxisCoverage] = []
    bumped = False
    for entry in intent.axes_coverage:
        prefix = _axis_prefix(entry.axis)
        if prefix == active_prefix and entry.score < floor:
            new_axes.append(entry.model_copy(update={"score": floor}))
            bumped = True
        else:
            new_axes.append(entry)
    if not bumped:
        return intent
    logger.warning(
        "brain_b axes_coverage floor-bumped active axis axis=%s floor=%s",
        active_prefix,
        floor,
    )
    return intent.model_copy(update={"axes_coverage": new_axes})


_ROTATION_TRIGGER_COUNT = 2


_CLOSING_PROSE_PHRASES: tuple[str, ...] = (
    "i have enough to wrap up",
    "thank you for the time",
    "thanks for the time",
    "ready to wrap",
    "we can wrap",
    "i'll close us out",
    "i will close us out",
    "i think we are done",
    "i think that's all i need",
    "i think that is all i need",
    "we're done here",
    "we are done here",
)


def _apply_closing_prose_guard(
    intent: BrainBIntent,
    *,
    reply_text: str,
) -> BrainBIntent:
    """Force ``should_close`` and a closing chip set when prose closes the turn.

    Brain A occasionally writes closing language ("I have enough to wrap up.
    Thank you for the time.") even when Brain B's structured intent still
    reports ``should_close=False`` and emits substantive follow-up chips. The
    operator console then sees an active session with closing prose; the
    participant sees quote-back chips for a turn that just told them goodbye.

    This guard reconciles the two by scanning ``reply_text`` against a small
    allowlist of closing phrases. When any phrase matches and the intent
    still has ``should_close=False``, the guard rewrites ``should_close`` to
    True and overwrites ``get_user_input.options`` to the canonical closing
    set ``["End conversation", "Discuss this more."]``. ``allow_free_text``
    is preserved so the participant can still explain why they want to keep
    going. A WARNING is logged for audit so live ops can see how often the
    guard fires.
    """
    if intent.should_close:
        return intent
    body = (reply_text or "").lower()
    if not body:
        return intent
    if not any(phrase in body for phrase in _CLOSING_PROSE_PHRASES):
        return intent
    closing_options = ["End conversation", _DISCUSS_MORE]
    new_get_user_input = intent.get_user_input.model_copy(
        update={"options": closing_options}
    )
    logger.warning("closing prose detected; forced should_close=true")
    return intent.model_copy(
        update={
            "should_close": True,
            "closing": True,
            "get_user_input": new_get_user_input,
        }
    )


def _force_axis_rotation(
    intent: BrainBIntent,
    *,
    rubric_axes: list[str],
    prior_active_axis_prefix: str,
    prior_consecutive_count: int,
    surface: Surface,
) -> tuple[BrainBIntent, bool]:
    """Rewrite ``active_axis`` when Brain B over-anchors past the rotation budget.

    The interviewer surface tracks how many consecutive prior agent turns
    stayed on the same active axis. When the count reaches
    ``_ROTATION_TRIGGER_COUNT`` and the model still emits the same axis prefix
    on this turn (the third in a row), the orchestrator overwrites
    ``active_axis`` with the lowest-numbered rubric axis whose score is 0.0.
    Designer turns (no rubric_axes) and surfaces that do not pass this
    context bypass the override.

    The override never reverses the model's positive scoring; it only swaps
    the chosen probe axis. If every rubric axis already has positive score,
    no rotation target exists and the intent is left as-is.

    Returns ``(intent, rotated)`` where ``rotated`` is True when the active
    axis was actually swapped. Callers use the flag to skip the substantive-
    turn floor on this turn so a freshly-rotated axis is not credited with
    evidence from the prior axis.
    """
    if prior_consecutive_count < _ROTATION_TRIGGER_COUNT:
        return intent, False
    if not prior_active_axis_prefix:
        return intent, False
    emitted_prefix = _axis_prefix(intent.active_axis)
    if not emitted_prefix or emitted_prefix != prior_active_axis_prefix:
        return intent, False

    score_by_prefix: dict[str, float] = {}
    for entry in intent.axes_coverage:
        prefix = _axis_prefix(entry.axis)
        if not prefix:
            continue
        score_by_prefix[prefix] = _clamp_score(entry.score)

    rotation_label = ""
    rotation_prefix = ""
    for raw_axis in rubric_axes:
        prefix = _axis_prefix(raw_axis)
        if not prefix or prefix == emitted_prefix:
            continue
        if score_by_prefix.get(prefix, 0.0) > 0.0:
            continue
        rotation_label = raw_axis
        rotation_prefix = prefix
        break

    if not rotation_prefix:
        return intent, False

    logger.warning(
        "brain_b axis rotation forced surface=%s prior_axis=%s consecutive=%s rotation_to=%s",
        surface,
        prior_active_axis_prefix,
        prior_consecutive_count,
        rotation_prefix,
    )
    return intent.model_copy(update={"active_axis": rotation_label}), True


def _is_substantive_turn(intent: BrainBIntent) -> bool:
    """Heuristic: did this turn produce evidence the rubric should credit?

    True when retrieval fired (Brain B believed grounding was worth fetching)
    OR when Brain B advanced any question's status to ``partial`` or
    ``satisfied`` (Brain B believed the participant gave usable evidence).
    A ``targeting`` emission alone is not enough; targeting just announces
    intent for the next turn, not evidence on this one.
    """
    if intent.retrieval_used:
        return True
    for entry in intent.question_coverage:
        if entry.status in {"partial", "satisfied"}:
            return True
    return False


def _finalize_valid_intent(
    intent: BrainBIntent,
    *,
    surface: Surface,
    tool_calls_made: list[ToolCallRecord],
    rubric_axes: list[str] | None,
    prior_axes_coverage: list[AxisCoverage] | None,
    close_guard_axes: list[str] | None,
    eligible_question_ids: list[str] | None,
    prior_question_coverage: list[QuestionCoverage] | None,
    prior_active_axis_prefix: str,
    prior_consecutive_active_axis_count: int,
) -> BrainBIntent:
    observed_chunks = _observed_retrieval_chunks(tool_calls_made)
    retrieval_used = any(call.name == "search_knowledge" for call in tool_calls_made)
    intent = intent.model_copy(
        update={
            "retrieval_used": retrieval_used,
            "retrieval_chunks": observed_chunks if retrieval_used else [],
        }
    )
    if rubric_axes is not None:
        intent = _normalize_axes_coverage(
            intent,
            rubric_axes=rubric_axes,
            prior_axes=prior_axes_coverage,
        )
    if close_guard_axes:
        intent = _enforce_close_guard(
            intent,
            close_guard_axes=close_guard_axes,
            surface=surface,
        )
    if eligible_question_ids is not None:
        eligible_ids = {
            qid.strip() for qid in eligible_question_ids if qid and qid.strip()
        }
        emitted_count = len(intent.question_coverage)
        merged_question_coverage, merge_stats = _merge_question_coverage_with_stats(
            prior_question_coverage,
            intent.question_coverage,
            eligible_ids=eligible_ids,
        )
        intent = intent.model_copy(update={"question_coverage": merged_question_coverage})
        logger.info(
            "brain_b question_coverage merge surface=%s emitted=%s dropped_out_of_bank=%s regressions_overridden=%s final=%s",
            surface,
            emitted_count,
            merge_stats.dropped_out_of_bank,
            merge_stats.regressions_overridden,
            merge_stats.final_count,
        )
    if rubric_axes is not None:
        intent, rotation_forced = _force_axis_rotation(
            intent,
            rubric_axes=rubric_axes,
            prior_active_axis_prefix=prior_active_axis_prefix,
            prior_consecutive_count=prior_consecutive_active_axis_count,
            surface=surface,
        )
        if not rotation_forced:
            intent = _floor_active_axis(intent, rubric_axes=rubric_axes)
    return intent


def _enforce_close_guard(
    intent: BrainBIntent,
    *,
    close_guard_axes: list[str] | None,
    surface: Surface,
) -> BrainBIntent:
    if not intent.should_close:
        return intent
    if not close_guard_axes:
        return intent
    score_by_prefix: dict[str, float] = {}
    for entry in intent.axes_coverage:
        prefix = _axis_prefix(entry.axis)
        if not prefix:
            continue
        score_by_prefix[prefix] = _clamp_score(entry.score)
    for raw_guard in close_guard_axes:
        prefix = _axis_prefix(raw_guard)
        if not prefix:
            continue
        score = score_by_prefix.get(prefix)
        if score is None or score == 0.0:
            logger.warning(
                "close guard flipped should_close=False surface=%s reason=axis_%s_is_zero",
                surface,
                prefix,
            )
            return intent.model_copy(update={"should_close": False})
    return intent


_QUESTION_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"targeting", "partial", "satisfied", "skipped"},
    "targeting": {"targeting", "partial", "satisfied", "skipped"},
    "partial": {"partial", "satisfied", "skipped"},
    "satisfied": {"satisfied"},
    "skipped": {"skipped", "partial"},
}


def _question_transition_allowed(previous: str, proposed: str) -> bool:
    if proposed == "pending":
        return previous == "pending"
    allowed = _QUESTION_TRANSITIONS.get(previous, set())
    return proposed in allowed


def _merge_question_coverage_with_stats(
    prior_question_coverage: list[QuestionCoverage] | None,
    emitted_question_coverage: list[QuestionCoverage] | None,
    *,
    eligible_ids: set[str],
) -> tuple[list[QuestionCoverage], _QuestionCoverageMergeStats]:
    stats = _QuestionCoverageMergeStats(
        emitted_count=len(emitted_question_coverage or [])
    )
    merged_by_id: dict[str, QuestionCoverage] = {}
    order: list[str] = []
    for entry in prior_question_coverage or []:
        question_id = entry.question_id.strip()
        if not question_id or question_id not in eligible_ids:
            continue
        merged_by_id[question_id] = entry.model_copy(deep=True)
        if question_id not in order:
            order.append(question_id)

    newest_targeting_id = ""
    for emitted in emitted_question_coverage or []:
        question_id = emitted.question_id.strip()
        if not question_id or question_id not in eligible_ids:
            stats.dropped_out_of_bank += 1
            continue
        prior = merged_by_id.get(question_id)
        prior_status = prior.status if prior is not None else "pending"
        proposed_status = emitted.status
        if not _question_transition_allowed(prior_status, proposed_status):
            stats.regressions_overridden += 1
            continue
        if prior is None and proposed_status == "pending":
            continue
        merged_by_id[question_id] = emitted.model_copy(
            update={"question_id": question_id},
            deep=True,
        )
        if question_id not in order:
            order.append(question_id)
        if proposed_status == "targeting":
            newest_targeting_id = question_id

    targeting_ids = [
        question_id
        for question_id in order
        if merged_by_id.get(question_id) is not None
        and merged_by_id[question_id].status == "targeting"
    ]
    if len(targeting_ids) > 1:
        targeting_winner = newest_targeting_id or targeting_ids[-1]
        for question_id in targeting_ids:
            if question_id == targeting_winner:
                continue
            current = merged_by_id[question_id]
            merged_by_id[question_id] = current.model_copy(
                update={"status": "partial"},
                deep=True,
            )

    merged = [merged_by_id[question_id] for question_id in order if question_id in merged_by_id]
    stats.final_count = len(merged)
    return merged, stats


def _merge_question_coverage(
    prior_question_coverage: list[QuestionCoverage] | None,
    emitted_question_coverage: list[QuestionCoverage] | None,
    *,
    eligible_ids: set[str],
) -> list[QuestionCoverage]:
    """Merge Brain B's per-turn question coverage emission into prior state."""
    merged, _stats = _merge_question_coverage_with_stats(
        prior_question_coverage,
        emitted_question_coverage,
        eligible_ids=eligible_ids,
    )
    return merged


async def run_brain_b_with_tools(
    *,
    surface: Surface,
    system_context: list[str],
    transcript_tail: list[dict[str, Any]],
    registry: ToolRegistry,
    router,
    max_tool_calls: int = 4,
    max_parse_retries: int = 1,
    rubric_axes: list[str] | None = None,
    prior_axes_coverage: list[AxisCoverage] | None = None,
    close_guard_axes: list[str] | None = None,
    eligible_question_ids: list[str] | None = None,
    prior_question_coverage: list[QuestionCoverage] | None = None,
    reasoning_budget_tokens: int | None = None,
    prior_active_axis_prefix: str = "",
    prior_consecutive_active_axis_count: int = 0,
    last_participant_message: str = "",
    participant_extracted_concepts: list[str] | None = None,
) -> BrainBLoopResult:
    """Single tool-calling loop shared by Designer and Interviewer Brain B.

    The loop alternates between completion calls and tool dispatches until the
    model emits a terminal message (no ``tool_calls``). The terminal message
    is parsed as ``BrainBIntent``; parse failures trigger up to
    ``max_parse_retries`` recovery iterations before the loop raises.
    ``max_tool_calls`` bounds total tool invocations per turn so latency stays
    predictable. ``retrieval_used`` and ``retrieval_chunks`` on the returned
    intent are overridden from observed ``search_knowledge`` calls so the
    audit trail reflects reality, not model self-report.

    When ``rubric_axes`` is provided, the returned intent's ``axes_coverage``
    is rewritten to carry one entry per rubric axis in declaration order, with
    scores clamped to ``[0.0, 1.0]`` and monotonically non-decreasing against
    ``prior_axes_coverage`` (an empty emission inherits the prior; an absent
    prior defaults to ``0.0``). When ``close_guard_axes`` is truthy and the
    model emitted ``should_close=True``, the guard flips it back to ``False``
    whenever any listed axis is missing or scored ``0.0``; the flip is logged
    for audit. Both knobs default to ``None`` so the Designer surface keeps
    its existing permissive behavior.

    When ``eligible_question_ids`` is provided, Interviewer ``question_coverage``
    is merged into ``prior_question_coverage`` with out-of-bank emissions
    dropped, terminal statuses protected, and only one ``targeting`` entry
    retained. ``None`` disables the enforcement path for surfaces that do not
    use a question bank.
    """
    system_prompt = _prompt_path(surface).read_text(encoding="utf-8").strip()
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for extra in system_context:
        if extra:
            messages.append({"role": "system", "content": extra})
    messages.extend(transcript_tail)

    registry_tools_schema = registry.openai_schema() if not registry.is_empty() else []
    output_tool_schema = _brain_b_output_tool_schema()
    tool_calls_made: list[ToolCallRecord] = []
    parse_retries = 0
    raw_output = ""
    last_exc: Exception | None = None

    # LM Studio handles OpenAI tool calls more reliably than response_format
    # on the long Brain B prompt. Retrieval and graph lookups remain normal
    # tools. Brain B's final handoff is also a tool call
    # (emit_brain_b_intent), with forced tool_choice used only after a parse
    # failure so repair cannot drift into prose.
    #
    # Gemma can spend the whole completion budget in hidden reasoning before
    # reaching a tool call on the long Brain B prompt. Tool mode is therefore
    # run without thinking; direct probes show the same model emits OpenAI
    # tool_calls promptly with thinking disabled.
    max_iterations = max_tool_calls + max_parse_retries + 2
    for iteration in range(max_iterations):
        terminal_only = parse_retries > 0
        thinking_enabled = False
        completion_token_budget = (
            reasoning_completion_tokens(reasoning_budget_tokens)
            if thinking_enabled
            else repair_completion_tokens()
        )
        # Gemma's llama-server chat template treats a trailing assistant
        # message as a partial-response prefill and rejects the request when
        # ``enable_thinking=true`` is also set. Brain B's transcript_tail
        # frequently ends on the prior agent reply (the post-turn background
        # plans the NEXT probe immediately after Mira speaks), so the
        # sanitizer wraps the trailing assistant into a follow-up user turn
        # before every thinking-enabled call. The resolved messages list is
        # request-local; the loop's own ``messages`` list keeps appending
        # tool-call records for the next iteration.
        request_messages = (
            sanitize_thinking_messages(messages)
            if thinking_enabled
            else list(messages)
        )
        if (
            not thinking_enabled
            and request_messages
            and request_messages[-1].get("role") == "assistant"
            and request_messages[-1].get("tool_calls")
        ):
            sanitize_thinking_messages(request_messages)
        completion_kwargs: dict[str, Any] = {
            "model": "mira-scientist",
            "messages": request_messages,
            "stream": False,
            "max_tokens": completion_token_budget,
            "metadata": {
                "surface": surface,
                "brain": "B",
                "iteration": iteration,
                "terminal_only": terminal_only,
                "thinking_enabled": thinking_enabled,
            },
        }
        if thinking_enabled:
            set_lmstudio_thinking(
                completion_kwargs,
                enabled=True,
                min_tokens=completion_token_budget,
            )
        else:
            set_lmstudio_thinking(completion_kwargs, enabled=False)
        if terminal_only:
            completion_kwargs["tools"] = [output_tool_schema]
            completion_kwargs["tool_choice"] = _forced_output_tool_choice()
        else:
            completion_kwargs["tools"] = [*registry_tools_schema, output_tool_schema]

        start_time = time.monotonic()
        response = await router.acompletion(**completion_kwargs)
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        message = _extract_message(response)
        tool_calls = _normalize_tool_calls(message)
        _log_brain_b_llm_result(
            surface=surface,
            iteration=iteration,
            terminal_only=terminal_only,
            thinking_enabled=thinking_enabled,
            has_tools=bool(completion_kwargs.get("tools")),
            has_response_format=bool(completion_kwargs.get("response_format")),
            elapsed_ms=elapsed_ms,
            response=response,
            message=message,
            tool_calls=tool_calls,
        )

        output_tool_call: dict[str, Any] | None = None
        if tool_calls:
            for call in tool_calls:
                if _tool_call_name(call) == _EMIT_INTENT_TOOL_NAME:
                    output_tool_call = call
                    break

        if output_tool_call is not None:
            raw_output = _tool_call_arguments(output_tool_call)
            normalized = _normalize_discuss_more(
                raw_output,
                last_participant_message=last_participant_message,
                participant_extracted_concepts=participant_extracted_concepts,
            )
            try:
                intent = BrainBIntent.model_validate_json(normalized)
            except (ValidationError, ValueError) as exc:
                last_exc = exc
                if parse_retries >= max_parse_retries:
                    break
                parse_retries += 1
                messages = _compact_brain_b_repair_messages(
                    system_context=system_context,
                    transcript_tail=transcript_tail,
                    tool_calls_made=tool_calls_made,
                    validation_error=exc,
                )
                continue

            intent = _finalize_valid_intent(
                intent,
                surface=surface,
                tool_calls_made=tool_calls_made,
                rubric_axes=rubric_axes,
                prior_axes_coverage=prior_axes_coverage,
                close_guard_axes=close_guard_axes,
                eligible_question_ids=eligible_question_ids,
                prior_question_coverage=prior_question_coverage,
                prior_active_axis_prefix=prior_active_axis_prefix,
                prior_consecutive_active_axis_count=prior_consecutive_active_axis_count,
            )
            _log_brain_b_summary(
                surface=surface,
                iterations=iteration + 1,
                tool_calls=tool_calls_made,
                intent=intent,
                parse_retries=parse_retries,
            )
            return BrainBLoopResult(intent=intent, tool_calls=tool_calls_made, raw_output=raw_output)

        if tool_calls:
            # Local models occasionally emit tool_calls for output-contract
            # fields like ``get_user_input``. Drop unknown names so the
            # turn proceeds on whatever content is also present; if there
            # is no content, the existing parse-retry path will force a
            # terminal output tool call. The dropped call never reaches the assistant
            # message we append below, which keeps the OpenAI tool_call_id
            # ↔ tool message pairing consistent.
            filtered_tool_calls: list[dict[str, Any]] = []
            for call in tool_calls:
                candidate_name = _tool_call_name(call)
                if candidate_name and candidate_name in registry:
                    filtered_tool_calls.append(call)
                else:
                    logger.warning(
                        "brain_b dropped unknown tool_call surface=%s name=%s known=%s",
                        surface,
                        candidate_name or "<empty>",
                        sorted(registry.names()),
                    )
            tool_calls = filtered_tool_calls

        if tool_calls:
            if len(tool_calls_made) + len(tool_calls) > max_tool_calls:
                raise BrainBToolBudgetExceeded(
                    f"Brain B exceeded tool-call budget of {max_tool_calls}",
                    raw_output=_message_content(message),
                    surface=surface,
                )
            messages.append(
                {
                    "role": "assistant",
                    "content": message.get("content") or "",
                    "tool_calls": tool_calls,
                }
            )
            for call in tool_calls:
                name = _tool_call_name(call)
                arguments_raw = _tool_call_arguments(call)
                tool_call_id = str(call.get("id") or "")
                try:
                    result = await registry.dispatch(name, arguments_raw)
                    result_json = json.dumps(result, default=str)
                except ToolDispatchError as exc:
                    result = {"error": str(exc), "tool": exc.tool}
                    result_json = json.dumps(result)
                    logger.warning(
                        "brain_b tool dispatch error surface=%s tool=%s err=%s",
                        surface,
                        exc.tool,
                        exc,
                    )
                try:
                    parsed_args = (
                        json.loads(arguments_raw)
                        if isinstance(arguments_raw, str) and arguments_raw.strip()
                        else {}
                    )
                    if not isinstance(parsed_args, dict):
                        parsed_args = {"raw": arguments_raw}
                except json.JSONDecodeError:
                    parsed_args = {"raw": arguments_raw}
                tool_calls_made.append(
                    ToolCallRecord(
                        name=name,
                        arguments=parsed_args,
                        result=result,
                        result_summary=_summarize(result),
                    )
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": name,
                        "content": result_json,
                    }
                )
            continue

        raw_output = _message_content(message)
        normalized = _normalize_discuss_more(
            raw_output,
            last_participant_message=last_participant_message,
            participant_extracted_concepts=participant_extracted_concepts,
        )
        try:
            intent = BrainBIntent.model_validate_json(normalized)
        except (ValidationError, ValueError) as exc:
            last_exc = exc
            if parse_retries >= max_parse_retries:
                break
            parse_retries += 1
            messages = _compact_brain_b_repair_messages(
                system_context=system_context,
                transcript_tail=transcript_tail,
                tool_calls_made=tool_calls_made,
                validation_error=exc,
            )
            continue

        intent = _finalize_valid_intent(
            intent,
            surface=surface,
            tool_calls_made=tool_calls_made,
            rubric_axes=rubric_axes,
            prior_axes_coverage=prior_axes_coverage,
            close_guard_axes=close_guard_axes,
            eligible_question_ids=eligible_question_ids,
            prior_question_coverage=prior_question_coverage,
            prior_active_axis_prefix=prior_active_axis_prefix,
            prior_consecutive_active_axis_count=prior_consecutive_active_axis_count,
        )
        _log_brain_b_summary(
            surface=surface,
            iterations=iteration + 1,
            tool_calls=tool_calls_made,
            intent=intent,
            parse_retries=parse_retries,
        )
        return BrainBLoopResult(intent=intent, tool_calls=tool_calls_made, raw_output=raw_output)

    raise BrainBLoopError(
        f"Brain B failed to produce a valid intent after "
        f"{len(tool_calls_made)} tool calls and {parse_retries} parse retries: {last_exc}",
        raw_output=raw_output,
        surface=surface,
    )
