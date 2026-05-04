from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

__all__ = ["GetUserInputOptions", "DISCUSS_MORE_OPTION"]

DISCUSS_MORE_OPTION = "Discuss this more."


class GetUserInputOptions(BaseModel):
    """Chip-set contract emitted by Brain B and rendered verbatim by Brain A.

    Substantive turns carry 3-5 options; closing turns collapse to exactly
    two: a single closing affordance plus the canonical
    ``"Discuss this more."``. The final option MUST be literally
    ``"Discuss this more."`` so the participant always has an escape hatch
    into free conversation. See designer-interview §7 and lifecycles §2.
    """

    question: str
    options: list[str] = Field(min_length=2, max_length=5)
    allow_free_text: bool = True

    @model_validator(mode="after")
    def _require_discuss_more_last(self) -> "GetUserInputOptions":
        if self.options[-1] != DISCUSS_MORE_OPTION:
            raise ValueError(
                f"GetUserInputOptions.options[-1] must be exactly {DISCUSS_MORE_OPTION!r}"
            )
        return self
