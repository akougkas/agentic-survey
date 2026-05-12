from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Sequence

from pydantic import BaseModel, Field

from agentic_survey.llm.pool import EndpointPool

AgentRole = Literal["chatter", "scientist", "validator", "analyst", "embedding", "ingest"]
Endpoint = Literal["chatter", "scientist"]
ReasoningMode = Literal["off", "on", "budget"]
ReasoningKwarg = Literal["enable_thinking", "reasoning_effort", "none"]

AGENT_ROLES: tuple[AgentRole, ...] = (
    "chatter",
    "scientist",
    "validator",
    "analyst",
    "embedding",
    "ingest",
)


def _timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()


class CatalogEntry(BaseModel):
    catalog_id: str
    role: AgentRole
    endpoint: Endpoint
    model_id: str
    label: str
    notes: str | None = None
    enabled: bool = True
    is_default: bool = False
    reasoning_mode: ReasoningMode = "off"
    reasoning_budget_tokens: int | None = Field(default=None, ge=1)
    reasoning_kwarg: ReasoningKwarg = "none"
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    created_at: str = Field(default_factory=_timestamp)
    updated_at: str = Field(default_factory=_timestamp)


@dataclass(slots=True)
class CatalogResolution:
    role: AgentRole
    source: Literal["campaign_override", "catalog_default", "env_fallback"]
    catalog_id: str | None
    endpoint: Endpoint
    model_id: str
    api_base: str
    reasoning_mode: ReasoningMode = "off"
    reasoning_budget_tokens: int | None = None
    reasoning_kwarg: ReasoningKwarg = "none"
    temperature: float | None = None


def seed_entries() -> list[CatalogEntry]:
    """Canonical brain-aligned catalog.

    Two logical brains, each independently configurable:

    * ``chatter`` — Brain A. Mira's voice. Streams visible replies to the
      participant. Reasoning always off; temperature reads from
      ``settings.chatter_temperature``.
    * ``scientist`` — Brain B + Validator + Analyst + Ingest. Tool-using,
      analytical, runs in the background. Temperature reads from
      ``settings.scientist_temperature``. Reasoning mode reads from
      ``settings.scientist_supports_reasoning``: when False the catalog
      clamps every scientist-family role to ``reasoning_mode="off"`` so a
      non-thinking model (Gemma, Qwen3-base, AgenticQwen) does not burn
      per-turn latency on stream-of-consciousness deliberation.

    Both brains can share a single physical endpoint (e.g., one llama.cpp
    server with ``--parallel N``) by pointing both URLs at the same host;
    per-call temperature and ``enable_thinking`` overrides differentiate the
    two brains' request shapes.
    """
    from agentic_survey.config import get_settings

    settings = get_settings()
    chatter_model = settings.chatter_model
    scientist_model = settings.scientist_model
    embedding_model = settings.embedding_model
    chatter_temperature = settings.chatter_temperature
    scientist_temperature = settings.scientist_temperature
    scientist_reasoning: ReasoningMode = (
        "on" if settings.scientist_supports_reasoning else "off"
    )
    context_note = (
        f"Scientist host context window is configured as "
        f"{settings.scientist_context_window_tokens} tokens; per-call completion "
        f"caps stay separate."
    )
    return [
        CatalogEntry(
            catalog_id="chatter-default",
            role="chatter",
            endpoint="chatter",
            model_id=chatter_model,
            label=f"{chatter_model} (Brain A — Mira's voice)",
            is_default=True,
            reasoning_mode="off",
            reasoning_kwarg="enable_thinking",
            temperature=chatter_temperature,
        ),
        CatalogEntry(
            catalog_id="scientist-default",
            role="scientist",
            endpoint="scientist",
            model_id=scientist_model,
            label=f"{scientist_model} (Brain B — planner + analyst)",
            notes=context_note,
            is_default=True,
            reasoning_mode=scientist_reasoning,
            reasoning_kwarg="enable_thinking",
            temperature=scientist_temperature,
        ),
        CatalogEntry(
            catalog_id="scientist-validator",
            role="validator",
            endpoint="scientist",
            model_id=scientist_model,
            label=f"{scientist_model} (Validator — compact JSON)",
            notes=context_note,
            is_default=True,
            reasoning_mode="off",
            reasoning_kwarg="enable_thinking",
            temperature=0.0,
        ),
        CatalogEntry(
            catalog_id="scientist-analyst",
            role="analyst",
            endpoint="scientist",
            model_id=scientist_model,
            label=f"{scientist_model} (Analyst)",
            notes=context_note,
            is_default=True,
            reasoning_mode=scientist_reasoning,
            reasoning_kwarg="enable_thinking",
            temperature=scientist_temperature,
        ),
        CatalogEntry(
            catalog_id="scientist-ingest",
            role="ingest",
            endpoint="scientist",
            model_id=scientist_model,
            label=f"{scientist_model} (Ingest)",
            notes=context_note,
            is_default=True,
            reasoning_mode="off",
            reasoning_kwarg="enable_thinking",
            temperature=0.0,
        ),
        CatalogEntry(
            catalog_id="scientist-embedding",
            role="embedding",
            endpoint="scientist",
            model_id=embedding_model,
            label=f"{embedding_model} (Embeddings)",
            is_default=True,
        ),
    ]


def resolve(
    role: AgentRole,
    *,
    campaign_models: dict[str, str] | None,
    catalog: Sequence[CatalogEntry],
    pool: EndpointPool,
) -> CatalogResolution:
    if campaign_models and (override_id := campaign_models.get(role)):
        entry = next(
            (
                candidate
                for candidate in catalog
                if candidate.catalog_id == override_id and candidate.role == role and candidate.enabled
            ),
            None,
        )
        if entry is not None:
            return CatalogResolution(
                role=role,
                source="campaign_override",
                catalog_id=entry.catalog_id,
                endpoint=entry.endpoint,
                model_id=entry.model_id,
                api_base=_endpoint_url(entry.endpoint, pool),
                reasoning_mode=entry.reasoning_mode,
                reasoning_budget_tokens=entry.reasoning_budget_tokens,
                reasoning_kwarg=entry.reasoning_kwarg,
                temperature=entry.temperature,
            )

    entry = next(
        (
            candidate
            for candidate in catalog
            if candidate.role == role and candidate.is_default and candidate.enabled
        ),
        None,
    )
    if entry is not None:
        return CatalogResolution(
            role=role,
            source="catalog_default",
            catalog_id=entry.catalog_id,
            endpoint=entry.endpoint,
            model_id=entry.model_id,
            api_base=_endpoint_url(entry.endpoint, pool),
            reasoning_mode=entry.reasoning_mode,
            reasoning_budget_tokens=entry.reasoning_budget_tokens,
            reasoning_kwarg=entry.reasoning_kwarg,
            temperature=entry.temperature,
        )

    endpoint_name = _fallback_endpoint(role)
    endpoint = pool.get_endpoint(endpoint_name)
    return CatalogResolution(
        role=role,
        source="env_fallback",
        catalog_id=None,
        endpoint=endpoint_name,
        model_id=endpoint.model,
        api_base=endpoint.base_url,
    )


def _endpoint_url(endpoint: Endpoint, pool: EndpointPool) -> str:
    return pool.get_endpoint(endpoint).base_url


def _fallback_endpoint(role: AgentRole) -> Endpoint:
    if role == "chatter":
        return "chatter"
    return "scientist"
