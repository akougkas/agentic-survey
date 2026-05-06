from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from agentic_survey.agents.base import BaseAgent, PromptBundle
from agentic_survey.llm.client import ChatMessage, LLMClient, LLMUnavailable
from agentic_survey.llm.pool import AgentRole
from agentic_survey.repository import Campaign, OutlineArtifact

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "You are the silent Validator. You never reply to the participant. "
    "Grade the participant's most recent answer and extract research-graph concepts. "
    "Return ONLY a single compact JSON object and nothing else. No prose, no markdown fences. "
    "The JSON object must have exactly these keys: "
    "coverage_score (0.0-1.0), quality_score (0.0-1.0), follow_up_needed (bool), "
    "follow_up_reason (short string), is_spam (bool), "
    "extracted_concepts (array of {label,type}), "
    "extracted_relations (array of {from,to,kind,confidence}). "
    "Scores reward concrete, specific answers tied to real workflows. "
    "Be decisive; do not ruminate."
)


@dataclass(slots=True)
class ValidationResult:
    coverage_score: float = 0.0
    quality_score: float = 0.0
    follow_up_needed: bool = False
    follow_up_reason: str = ""
    is_spam: bool = False
    extracted_concepts: list[dict] = field(default_factory=list)
    extracted_relations: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "coverage_score": round(self.coverage_score, 3),
            "quality_score": round(self.quality_score, 3),
            "follow_up_needed": self.follow_up_needed,
            "follow_up_reason": self.follow_up_reason,
            "is_spam": self.is_spam,
            "extracted_concepts": list(self.extracted_concepts),
            "extracted_relations": list(self.extracted_relations),
        }


class Validator(BaseAgent):
    name = "validator"
    prompt = PromptBundle(
        system=SYSTEM_PROMPT,
        purpose="Silent per-turn grading and concept extraction.",
    )

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm

    async def validate(
        self,
        *,
        campaign: Campaign,
        content: str,
        outline: OutlineArtifact,
        previous_agent_question: str,
    ) -> ValidationResult:
        if self._llm is None:
            raise LLMUnavailable("validator has no llm client configured")
        return await self._llm_validate(
            campaign=campaign,
            content=content,
            outline=outline,
            previous_agent_question=previous_agent_question,
        )

    async def _llm_validate(
        self,
        *,
        campaign: Campaign,
        content: str,
        outline: OutlineArtifact,
        previous_agent_question: str,
    ) -> ValidationResult:
        assert self._llm is not None
        objectives = "\n".join(f"- {obj}" for obj in outline.objectives)
        context = (
            f"Objectives:\n{objectives}\n\n"
            f"Mira just asked: {previous_agent_question}\n\n"
            f"Participant answer:\n{content}\n"
        )
        messages = [
            ChatMessage(role="system", content=SYSTEM_PROMPT),
            ChatMessage(role="user", content=context),
        ]
        raw = await self._llm.chat(
            AgentRole.VALIDATOR,
            messages,
            campaign=campaign,
            temperature=0.0,
            max_tokens=1024,
            disable_reasoning=True,
        )
        try:
            return self._parse(raw.content)
        except LLMUnavailable as exc:
            logger.warning(
                "validator output parse failed; requesting JSON repair err=%s",
                exc,
            )
            repair_messages = [
                ChatMessage(
                    role="system",
                    content=(
                        "Repair malformed Validator JSON. Return only one valid compact JSON "
                        "object with exactly the Validator keys. Preserve any recoverable scores, "
                        "concepts, and relations. If a field is corrupt, replace it with a safe "
                        "empty value of the right type."
                    ),
                ),
                ChatMessage(
                    role="user",
                    content=(
                        f"Original participant answer:\n{content}\n\n"
                        f"Malformed Validator output:\n{raw.content}\n"
                    ),
                ),
            ]
            repaired = await self._llm.chat(
                AgentRole.VALIDATOR,
                repair_messages,
                campaign=campaign,
                temperature=0.0,
                max_tokens=1024,
                disable_reasoning=True,
            )
            return self._parse(repaired.content)

    def _parse(self, raw: str) -> ValidationResult:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
            if not match:
                raise LLMUnavailable(f"validator output was not valid JSON: {raw!r}")
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError as exc:
                raise LLMUnavailable(f"validator output JSON parse failed: {raw!r}") from exc
        return ValidationResult(
            coverage_score=float(payload.get("coverage_score", 0.5) or 0.0),
            quality_score=float(payload.get("quality_score", 0.5) or 0.0),
            follow_up_needed=bool(payload.get("follow_up_needed", False)),
            follow_up_reason=str(payload.get("follow_up_reason", "") or ""),
            is_spam=bool(payload.get("is_spam", False)),
            extracted_concepts=list(payload.get("extracted_concepts", []) or []),
            extracted_relations=list(payload.get("extracted_relations", []) or []),
        )
