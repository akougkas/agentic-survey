from __future__ import annotations

import json
import re

from agentic_survey.agents.base import BaseAgent, PromptBundle, load_prompt_text
from agentic_survey.llm.client import ChatMessage, LLMClient, LLMUnavailable
from agentic_survey.llm.catalog import AgentRole as CatalogRole
from agentic_survey.llm.pool import AgentRole
from agentic_survey.repository import Campaign, DesignerSession, OutlineArtifact


DESIGNER_REPLY_PROMPT = load_prompt_text("designer_brain_a.md")

DESIGNER_OUTLINE_PROMPT = (
    load_prompt_text("designer_brain_b.md")
    + "\n\n"
    + "You are turning the design transcript into the current outline state. "
    + "Return JSON only. Keep objectives and probes concrete, interviewable, and free of duplication. "
    + "The freshness query should stay compact. Preserve the backstage structure without making the visible study sound like a form."
)


def _designer_request_overrides(
    llm: LLMClient,
    *,
    campaign: Campaign,
    catalog_role: CatalogRole = "chatter",
) -> dict:
    endpoint = llm.resolve(
        AgentRole.DESIGNER,
        campaign=campaign,
        catalog_role=catalog_role,
    )
    model_name = endpoint.model.lower()
    if endpoint.name == "mini" and ("qwen" in model_name or "qwopus" in model_name):
        return {"chat_template_kwargs": {"enable_thinking": False}}
    return {}


class CampaignDesigner(BaseAgent):
    name = "campaign_designer"
    prompt = PromptBundle(
        system=DESIGNER_REPLY_PROMPT,
        purpose="Create campaign outlines and designer turns.",
    )

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm

    def opening_message(self, campaign: Campaign) -> str:
        return (
            f"I'm Mira. Let's turn {campaign.title} into a study the interviews can actually settle. "
            "Start with the question you need answered, even if the wording is still rough."
        )

    async def build_outline(self, campaign: Campaign, session: DesignerSession) -> OutlineArtifact:
        if self._llm is None:
            raise LLMUnavailable("designer has no llm client configured")
        return await self._llm_build_outline(campaign, session)

    async def next_reply(self, campaign: Campaign, session: DesignerSession, outline: OutlineArtifact) -> str:
        if self._llm is None:
            raise LLMUnavailable("designer has no llm client configured")
        return await self._llm_next_reply(campaign, session, outline)

    def is_ready_for_review(self, session: DesignerSession, outline: OutlineArtifact | None = None) -> bool:
        scientist_turns = [turn for turn in session.turns if turn.role == "scientist"]
        if len(scientist_turns) < 4:
            return False
        if outline is None:
            return True
        return bool(
            outline.scientist_summary.strip()
            and len(outline.objectives) >= 2
            and len(outline.probes) >= 3
            and outline.freshness_query.strip()
        )

    async def _llm_build_outline(self, campaign: Campaign, session: DesignerSession) -> OutlineArtifact:
        assert self._llm is not None
        transcript = "\n".join(
            f"{turn.role}: {turn.content.strip()}"
            for turn in session.turns
            if turn.content.strip()
        )
        outline = campaign.outline.model_copy(deep=True)
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "campaign_outline",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "scientist_summary": {"type": "string"},
                        "objectives": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 2,
                            "maxItems": 4,
                        },
                        "probes": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 3,
                            "maxItems": 5,
                        },
                        "freshness_query": {"type": "string"},
                    },
                    "required": [
                        "scientist_summary",
                        "objectives",
                        "probes",
                        "freshness_query",
                    ],
                },
            },
        }
        raw = await self._llm.chat(
            AgentRole.DESIGNER,
            [
                ChatMessage(role="system", content=DESIGNER_OUTLINE_PROMPT),
                ChatMessage(
                    role="user",
                    content=(
                        f"Campaign title: {campaign.title}\n"
                        f"Sample bounds: {campaign.min_n} to {campaign.max_n}\n\n"
                        f"Current outline summary: {outline.scientist_summary or 'none'}\n"
                        f"Current objectives: {outline.objectives or ['none']}\n"
                        f"Current probes: {outline.probes or ['none']}\n"
                        f"Current freshness query: {outline.freshness_query or 'none'}\n\n"
                        "Transcript:\n"
                        f"{transcript}"
                    ),
                ),
            ],
            campaign=campaign,
            catalog_role="scientist",
            temperature=0.2,
            max_tokens=8192,
            response_format=response_format,
            extra_body=_designer_request_overrides(
                self._llm,
                campaign=campaign,
                catalog_role="scientist",
            ),
        )
        try:
            payload = json.loads(raw.content)
        except json.JSONDecodeError as exc:
            raise LLMUnavailable(f"designer outline was not valid JSON: {raw.content!r}") from exc

        outline.objectives = _clean_lines(payload.get("objectives"), fallback=outline.objectives, limit=4)
        outline.probes = _clean_lines(payload.get("probes"), fallback=outline.probes, limit=5)
        outline.freshness_query = str(payload.get("freshness_query") or outline.freshness_query).strip()
        outline.scientist_summary = str(payload.get("scientist_summary") or outline.scientist_summary).strip()
        if not outline.objectives or not outline.probes or not outline.freshness_query:
            raise LLMUnavailable(f"designer outline missing required fields: {payload!r}")
        return outline

    async def _llm_next_reply(
        self,
        campaign: Campaign,
        session: DesignerSession,
        outline: OutlineArtifact,
    ) -> str:
        assert self._llm is not None
        transcript = [
            ChatMessage(role="system", content=DESIGNER_REPLY_PROMPT),
            ChatMessage(
                role="system",
                content=(
                    f"Campaign: {campaign.title}\n"
                    f"Sample bounds: {campaign.min_n} to {campaign.max_n}\n\n"
                    f"Current summary: {outline.scientist_summary or 'none'}\n"
                    f"Current objectives:\n- " + "\n- ".join(outline.objectives or ["none"]) + "\n\n"
                    f"Current probes:\n- " + "\n- ".join(outline.probes or ["none"]) + "\n\n"
                    f"Current freshness query: {outline.freshness_query or 'none'}\n\n"
                    "If the draft is nearly ready, focus on what evidence, sources, or segment boundary still needs sharpening."
                ),
            ),
        ]
        for turn in session.turns:
            role = "assistant" if turn.role == "designer" else "user"
            transcript.append(ChatMessage(role=role, content=turn.content))

        reply = await self._llm.chat(
            AgentRole.DESIGNER,
            transcript,
            campaign=campaign,
            temperature=0.25,
            max_tokens=8192,
            extra_body=_designer_request_overrides(self._llm, campaign=campaign),
        )
        reply_text = reply.content
        if _is_valid_designer_reply(reply_text):
            return reply_text

        repair_messages = list(transcript)
        repair_messages.append(
            ChatMessage(
                role="system",
                content=(
                    "Repair your previous draft. Output 2 or 3 sentences. "
                    "Reflect what is clearer, name what is still weak, then ask exactly one focused next question. "
                    "Under 120 words. No bullets or filler praise."
                ),
            )
        )
        repaired = await self._llm.chat(
            AgentRole.DESIGNER,
            repair_messages,
            campaign=campaign,
            temperature=0.15,
            max_tokens=8192,
            extra_body=_designer_request_overrides(self._llm, campaign=campaign),
        )
        repaired_text = repaired.content
        if _is_valid_designer_reply(repaired_text):
            return repaired_text
        raise LLMUnavailable(f"designer produced malformed reply after repair: {repaired_text!r}")


def _clean_lines(value: object, *, fallback: list[str], limit: int) -> list[str]:
    if not isinstance(value, list):
        return list(fallback)
    cleaned: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text or text in cleaned:
            continue
        cleaned.append(text)
    return cleaned[:limit] or list(fallback)


def _is_valid_designer_reply(text: str) -> bool:
    cleaned = " ".join(text.split())
    if not cleaned or cleaned.startswith(("-", "*")):
        return False
    lowered = cleaned.lower()
    if "great question" in lowered or "thanks for sharing" in lowered:
        return False
    if len(cleaned.split()) > 120:
        return False
    if cleaned.count("?") != 1 or not cleaned.endswith("?"):
        return False
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]
    if len(parts) < 1 or len(parts) > 3:
        return False
    if len(parts[0].split()) < 4:
        return False
    return True
