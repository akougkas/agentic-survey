from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Sequence

from pydantic import BaseModel, Field

from agentic_survey.llm.pool import EndpointPool

AgentRole = Literal["chatter", "scientist", "validator", "analyst", "embedding", "ingest"]
Endpoint = Literal["mini", "dynamo"]
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
    reasoning_budget_tokens: int | None = None
    reasoning_kwarg: ReasoningKwarg = "none"
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


def seed_entries() -> list[CatalogEntry]:
    """Canonical three-model catalog.

    Identity, endpoint routing, and model IDs all come from the Settings
    object. Brain A (chatter) lives on mini; every other LLM role collapses
    to the dynamo reasoning model; embeddings sit on dynamo too. Extend by
    editing env vars, not this list.
    """
    from agentic_survey.config import get_settings

    settings = get_settings()
    mini_model = settings.mini_model
    dynamo_model = settings.dynamo_model
    embedding_model = settings.embedding_model
    return [
        CatalogEntry(
            catalog_id="mini-chatter",
            role="chatter",
            endpoint="mini",
            model_id=mini_model,
            label=f"{mini_model} (Brain A on mini)",
            is_default=True,
        ),
        CatalogEntry(
            catalog_id="dynamo-scientist",
            role="scientist",
            endpoint="dynamo",
            model_id=dynamo_model,
            label=f"{dynamo_model} (Brain B on dynamo)",
            is_default=True,
            reasoning_mode="off",
            reasoning_kwarg="enable_thinking",
        ),
        CatalogEntry(
            catalog_id="dynamo-validator",
            role="validator",
            endpoint="dynamo",
            model_id=dynamo_model,
            label=f"{dynamo_model} (Validator on dynamo, reasoning budget)",
            is_default=True,
            reasoning_mode="off",
            reasoning_budget_tokens=None,
            reasoning_kwarg="enable_thinking",
        ),
        CatalogEntry(
            catalog_id="dynamo-analyst",
            role="analyst",
            endpoint="dynamo",
            model_id=dynamo_model,
            label=f"{dynamo_model} (Analyst on dynamo)",
            is_default=True,
            reasoning_mode="on",
            reasoning_kwarg="enable_thinking",
        ),
        CatalogEntry(
            catalog_id="dynamo-ingest",
            role="ingest",
            endpoint="dynamo",
            model_id=dynamo_model,
            label=f"{dynamo_model} (Ingest on dynamo)",
            is_default=True,
            reasoning_mode="off",
            reasoning_kwarg="enable_thinking",
        ),
        CatalogEntry(
            catalog_id="dynamo-embedding",
            role="embedding",
            endpoint="dynamo",
            model_id=embedding_model,
            label=f"{embedding_model} (Embeddings on dynamo)",
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
        return "mini"
    return "dynamo"
