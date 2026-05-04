from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_serializer, field_validator

__all__ = ["MethodObservation"]


class MethodObservation(BaseModel):
    id: str
    session_id: str
    campaign_id: str
    author: str
    body: str
    tags: list[str] = Field(default_factory=list)
    created_at: datetime

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must be non-empty")
        if len(stripped) > 4000:
            raise ValueError("must be 4000 characters or fewer")
        return stripped

    @field_validator("tags", mode="before")
    @classmethod
    def default_tags(cls, value: object) -> object:
        if value is None:
            return []
        return value

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in value:
            tag = raw.strip().lower()
            if not tag or tag in seen:
                continue
            normalized.append(tag)
            seen.add(tag)
        return normalized[:8]

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        return value.isoformat()
