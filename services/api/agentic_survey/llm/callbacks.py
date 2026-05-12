from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)
_audit_repository: Any | None = None


def set_llm_audit_repository(repository: Any | None) -> None:
    global _audit_repository
    _audit_repository = repository


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
    prompt_tokens = _coerce_int(_extract_value(usage, "prompt_tokens"))
    completion_tokens = _coerce_int(_extract_value(usage, "completion_tokens"))
    total_tokens = _coerce_int(_extract_value(usage, "total_tokens"))
    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens
    error_summary = None
    if error is not None:
        error_summary = str(error)
        if len(error_summary) > 500:
            error_summary = error_summary[:497] + "..."
    row = {
        "campaign_id": metadata.get("campaign_id"),
        "surface": metadata.get("surface") or "designer",
        "model_alias": kwargs.get("model") or metadata.get("router_alias") or "unknown",
        "endpoint": str(endpoint_used),
        "endpoint_model": metadata.get("endpoint_model"),
        "catalog_id": metadata.get("catalog_id"),
        "catalog_route": metadata.get("catalog_role") or metadata.get("route_source"),
        "brain": metadata.get("brain"),
        "role": metadata.get("catalog_role") or metadata.get("surface"),
        "session_id": metadata.get("session_id"),
        "turn_id": metadata.get("turn_id"),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "reasoning_tokens": _extract_value(completion_tokens_details, "reasoning_tokens"),
        "reasoning_metadata": {
            "reasoning_chars": len(reasoning_content) if reasoning_content is not None else None,
            "reasoning_mode": metadata.get("reasoning_mode"),
            "reasoning_kwarg": metadata.get("reasoning_kwarg"),
            "reasoning_budget_tokens": metadata.get("reasoning_budget_tokens"),
            "thinking_enabled": metadata.get("thinking_enabled"),
        },
        "latency_ms": _latency_ms(start_time, end_time),
        "status": status,
        "error_summary": error_summary,
        "metadata": metadata or {},
        "created_at": _coerce_datetime(end_time).isoformat(),
    }
    return row


def _persist_audit_row(row: dict[str, Any]) -> None:
    try:
        repository = _audit_repository
        if repository is None:
            from agentic_survey.repository import get_repository

            repository = get_repository()
        repository.record_llm_audit(row)
    except Exception:  # noqa: BLE001
        logger.exception("failed to persist llm_call_audit")


def success_callback(kwargs: dict[str, Any], completion_response: Any, start_time: Any, end_time: Any) -> None:
    row = _build_audit_row(
        kwargs=kwargs,
        completion_response=completion_response,
        start_time=start_time,
        end_time=end_time,
        status="ok",
    )
    _persist_audit_row(row)
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
    _persist_audit_row(row)
    logger.error("llm_call_audit %s", json.dumps(row, sort_keys=True, default=str))
