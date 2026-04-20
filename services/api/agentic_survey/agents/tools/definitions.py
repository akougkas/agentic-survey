from __future__ import annotations

from typing import Any, Awaitable, Callable

from agentic_survey.agents.tools.registry import MiraTool
from agentic_survey.domain.outline import OutlineArtifact
from agentic_survey.engine.session_policy import SessionSignals

__all__ = [
    "get_outline_state_tool",
    "get_session_signals_tool",
    "list_grounding_sources_tool",
    "list_participant_faq_tool",
    "propose_outline_patch_tool",
    "search_knowledge_tool",
]

SearchKnowledgeFn = Callable[[str, int], Awaitable[list[dict[str, Any]]]]
OutlineProvider = Callable[[], OutlineArtifact]
SourcesProvider = Callable[[], list[dict[str, Any]]]
SignalsProvider = Callable[[], SessionSignals]
PatchSink = Callable[[dict[str, Any]], None]


def search_knowledge_tool(*, search_fn: SearchKnowledgeFn) -> MiraTool:
    async def handler(args: dict[str, Any]) -> list[dict[str, Any]]:
        query = str(args.get("query", "")).strip()
        if not query:
            raise ValueError("query is required and must be non-empty")
        k_raw = args.get("k", 5)
        try:
            k = int(k_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"k must be an integer, got {k_raw!r}") from exc
        if k <= 0 or k > 20:
            raise ValueError("k must be in 1..20")
        return await search_fn(query, k)

    return MiraTool(
        name="search_knowledge",
        description=(
            "Retrieve up to k approved knowledge chunks relevant to the query. "
            "Call only when grounded facts materially improve your next design or interview move. "
            "Never search to prove a participant wrong. Results are ranked by relevance."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language query, 3-20 words.",
                },
                "k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 5,
                    "description": "Number of chunks to return.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=handler,
    )


def get_outline_state_tool(*, outline_provider: OutlineProvider) -> MiraTool:
    async def handler(_args: dict[str, Any]) -> dict[str, Any]:
        return outline_provider().model_dump()

    return MiraTool(
        name="get_outline_state",
        description=(
            "Return the current campaign outline (research question, sampling frame, "
            "axes, probes, risk register, FAQ, etc.). Use before proposing an outline patch."
        ),
        parameters_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=handler,
    )


def list_grounding_sources_tool(*, sources_provider: SourcesProvider) -> MiraTool:
    async def handler(_args: dict[str, Any]) -> list[dict[str, Any]]:
        return sources_provider()

    return MiraTool(
        name="list_grounding_sources",
        description=(
            "List the currently approved grounding sources attached to this campaign "
            "(title, kind, status). Useful for deciding whether a search is needed."
        ),
        parameters_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=handler,
    )


def list_participant_faq_tool(*, outline_provider: OutlineProvider) -> MiraTool:
    async def handler(_args: dict[str, Any]) -> list[dict[str, Any]]:
        return [entry.model_dump() for entry in outline_provider().participant_faq]

    return MiraTool(
        name="list_participant_faq",
        description=(
            "Return the curated participant FAQ attached to this campaign. "
            "Use this when the participant asks a logistics, sponsor, or "
            "study-about question; answer only from these entries."
        ),
        parameters_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=handler,
    )


def propose_outline_patch_tool(*, patch_sink: PatchSink) -> MiraTool:
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        sections = args.get("sections")
        if not isinstance(sections, list):
            raise ValueError("sections must be a list")
        patch_sink(args)
        return {"received": True, "section_count": len(sections)}

    return MiraTool(
        name="propose_outline_patch",
        description=(
            "Propose a structured patch to the outline. "
            "Sections are applied in order: op='replace' sets a value; "
            "op='append' extends lists; op='remove' filters list items by equality. "
            "Prefer small, targeted patches over whole-section replacements."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "section": {
                                "type": "string",
                                "description": "Outline field name to modify.",
                            },
                            "op": {
                                "type": "string",
                                "enum": ["replace", "append", "remove"],
                            },
                            "value": {
                                "description": "New value (replace), item to append, or item to remove.",
                            },
                        },
                        "required": ["section", "op"],
                        "additionalProperties": False,
                    },
                },
                "provenance": {
                    "type": "string",
                    "description": "Short rationale for the patch.",
                },
                "summary": {
                    "type": "string",
                    "description": "Optional human-readable summary.",
                },
            },
            "required": ["sections"],
            "additionalProperties": False,
        },
        handler=handler,
    )


def get_session_signals_tool(*, signals_provider: SignalsProvider) -> MiraTool:
    async def handler(_args: dict[str, Any]) -> dict[str, Any]:
        return signals_provider().model_dump()

    return MiraTool(
        name="get_session_signals",
        description=(
            "Return advisory session signals (turn count, coverage streak, "
            "objective hits). Signals are advisory; close authority is yours via should_close."
        ),
        parameters_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=handler,
    )
