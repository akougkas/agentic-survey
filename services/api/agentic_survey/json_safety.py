from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from math import isfinite
from typing import Any

from pydantic import BaseModel

__all__ = ["json_safe"]


def json_safe(value: Any, *, _depth: int = 0) -> Any:
    """Return a JSON/CBOR-safe representation of arbitrary callback metadata."""
    if _depth > 8:
        return str(value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if isfinite(value) else str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    if isinstance(value, Enum):
        return json_safe(value.value, _depth=_depth + 1)
    if isinstance(value, BaseModel):
        return json_safe(value.model_dump(mode="json"), _depth=_depth + 1)
    if is_dataclass(value) and not isinstance(value, type):
        return json_safe(asdict(value), _depth=_depth + 1)
    if isinstance(value, dict):
        return {
            str(key): json_safe(item, _depth=_depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(item, _depth=_depth + 1) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return json_safe(value.model_dump(mode="json"), _depth=_depth + 1)
        except Exception:  # noqa: BLE001
            pass
    if hasattr(value, "dict"):
        try:
            return json_safe(value.dict(), _depth=_depth + 1)
        except Exception:  # noqa: BLE001
            pass
    return str(value)
