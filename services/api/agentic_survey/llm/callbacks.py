from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def _extract_value(obj: object, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.now(tz=UTC)


def _latency_ms(start_time: Any, end_time: Any) -> int:
    start = _coerce_datetime(start_time)
    end = _coerce_datetime(end_time)
    return max(0, int((end - start).total_seconds() * 1000))


def _usage_from_response(completion_response: Any) -> Any:
    return _extract_value(completion_response, "usage") or {}


def _message_content(completion_response: Any) -> str | None:
    choices = _extract_value(completion_response, "choices") or []
    if not choices:
        return None
    message = _extract_value(choices[0], "message") or {}
    content = _extract_value(message, "content")
    if content is None:
        return None
    return str(content)


def _reasoning_content(completion_response: Any) -> str | None:
    choices = _extract_value(completion_response, "choices") or []
    if not choices:
        return None
    message = _extract_value(choices[0], "message") or {}
    reasoning = _extract_value(message, "reasoning_content")
    if reasoning is None:
        return None
    return str(reasoning)


def _metadata(kwargs: dict[str, Any]) -> dict[str, Any]:
    metadata = kwargs.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _build_audit_row(
    *,
    kwargs: dict[str, Any],
    completion_response: Any,
    start_time: Any,
    end_time: Any,
    status: str,
    error: Any = None,
) -> dict[str, Any]:
    metadata = _metadata(kwargs)
    usage = _usage_from_response(completion_response)
    completion_tokens_details = _extract_value(usage, "completion_tokens_details") or {}
    reasoning_content = _reasoning_content(completion_response)
    endpoint_used = (
        kwargs.get("api_base")
        or metadata.get("endpoint_name")
        or metadata.get("endpoint_model")
        or kwargs.get("model")
        or "unknown"
    )
    row = {
        "campaign": metadata.get("campaign_id"),
        "surface": metadata.get("surface") or "designer",
        "model": kwargs.get("model") or metadata.get("endpoint_model") or "unknown",
        "endpoint_used": str(endpoint_used),
        "brain": metadata.get("brain"),
        "session_id": metadata.get("session_id"),
        "turn_id": metadata.get("turn_id"),
        "prompt_tokens": _coerce_int(_extract_value(usage, "prompt_tokens")),
        "completion_tokens": _coerce_int(_extract_value(usage, "completion_tokens")),
        "reasoning_tokens": _extract_value(completion_tokens_details, "reasoning_tokens"),
        "reasoning_chars": len(reasoning_content) if reasoning_content is not None else None,
        "reasoning_content": reasoning_content,
        "latency_ms": _latency_ms(start_time, end_time),
        "status": status,
        "metadata": metadata or None,
        "created_at": _coerce_datetime(end_time).isoformat(),
        "raw_prompt": None,
        "raw_completion": _message_content(completion_response),
    }
    if error is not None:
        row["raw_completion"] = str(error)
    return row


def success_callback(kwargs: dict[str, Any], completion_response: Any, start_time: Any, end_time: Any) -> None:
    row = _build_audit_row(
        kwargs=kwargs,
        completion_response=completion_response,
        start_time=start_time,
        end_time=end_time,
        status="ok",
    )
    logger.warning("llm_call_audit %s", json.dumps(row, sort_keys=True, default=str))


def failure_callback(
    kwargs: dict[str, Any],
    completion_response: Any = None,
    start_time: Any = None,
    end_time: Any = None,
) -> None:
    row = _build_audit_row(
        kwargs=kwargs,
        completion_response=completion_response,
        start_time=start_time,
        end_time=end_time,
        status="failed",
        error=completion_response,
    )
    logger.error("llm_call_audit %s", json.dumps(row, sort_keys=True, default=str))
