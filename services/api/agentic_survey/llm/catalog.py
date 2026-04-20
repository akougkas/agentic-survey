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
    return [
        CatalogEntry(
            catalog_id="qwen-3.5-distilled",
            role="chatter",
            endpoint="mini",
            model_id="Qwen35-Distilled-i1-Q4_K_M",
            label="Qwen 3.5 Claude-distilled (reasoning, 262K)",
            notes="Always reasons; clean JSON output.",
            is_default=True,
        ),
        CatalogEntry(
            catalog_id="qwen-3.6-35b-a3b",
            role="chatter",
            endpoint="mini",
            model_id="Qwen3.6-35B-A3B-UD-Q4_K_XL",
            label="Qwen 3.6 35B-A3B (MoE, toggleable thinking, 262K)",
            notes="Native Qwen3 template; enable_thinking works.",
        ),
        CatalogEntry(
            catalog_id="gemma-4-26b",
            role="chatter",
            endpoint="mini",
            model_id="gemma-4-26B-A4B-it-Q4_K_M",
            label="Gemma-4 26B-A4B (VLM, reasoning, 262K)",
            notes="~23 GiB at 262K. Passed Designer flow in M1 driver test.",
        ),
        CatalogEntry(
            catalog_id="gemma-4-scientist",
            role="scientist",
            endpoint="mini",
            model_id="gemma-4-26B-A4B-it-Q4_K_M",
            label="Gemma-4 26B-A4B (scientist, reasoning on)",
            is_default=True,
            reasoning_mode="on",
            reasoning_kwarg="enable_thinking",
        ),
        CatalogEntry(
            catalog_id="qwen-3.5-distilled-scientist",
            role="scientist",
            endpoint="mini",
            model_id="Qwen35-Distilled-i1-Q4_K_M",
            label="Qwen 3.5 Distilled (scientist on mini)",
        ),
        CatalogEntry(
            catalog_id="nemotron-cascade",
            role="scientist",
            endpoint="dynamo",
            model_id="nemotron-cascade-2-30b-a3b-i1",
            label="Nemotron Cascade 2 30B-A3B (400K)",
            notes="Reasoning, tool_use, 400K context.",
        ),
        CatalogEntry(
            catalog_id="qwen-3.6-35b-a3b",
            role="scientist",
            endpoint="dynamo",
            model_id="qwen3.6-35b-a3b",
            label="Qwen 3.6 35B-A3B (on dynamo)",
        ),
        CatalogEntry(
            catalog_id="gemma-4-validator",
            role="validator",
            endpoint="mini",
            model_id="gemma-4-26B-A4B-it-Q4_K_M",
            label="Gemma-4 26B-A4B (validator, reasoning budget 2048)",
            is_default=True,
            reasoning_mode="budget",
            reasoning_budget_tokens=2048,
            reasoning_kwarg="enable_thinking",
        ),
        CatalogEntry(
            catalog_id="nemotron-cascade",
            role="validator",
            endpoint="dynamo",
            model_id="nemotron-cascade-2-30b-a3b-i1",
            label="Nemotron (validator)",
        ),
        CatalogEntry(
            catalog_id="gemma-4-analyst",
            role="analyst",
            endpoint="mini",
            model_id="gemma-4-26B-A4B-it-Q4_K_M",
            label="Gemma-4 26B-A4B (analyst, reasoning on)",
            is_default=True,
            reasoning_mode="on",
            reasoning_kwarg="enable_thinking",
        ),
        CatalogEntry(
            catalog_id="nemotron-cascade",
            role="analyst",
            endpoint="dynamo",
            model_id="nemotron-cascade-2-30b-a3b-i1",
            label="Nemotron (analyst)",
        ),
        CatalogEntry(
            catalog_id="nomic-v2-moe",
            role="embedding",
            endpoint="dynamo",
            model_id="text-embedding-nomic-embed-text-v2-moe",
            label="Nomic Embed v2 MoE (768-dim)",
            is_default=True,
        ),
        CatalogEntry(
            catalog_id="gemma-4-ingest",
            role="ingest",
            endpoint="mini",
            model_id="gemma-4-26B-A4B-it-Q4_K_M",
            label="Gemma-4 26B-A4B (ingest, reasoning off)",
            is_default=True,
            reasoning_mode="off",
            reasoning_kwarg="enable_thinking",
        ),
        CatalogEntry(
            catalog_id="nemotron-cascade",
            role="ingest",
            endpoint="dynamo",
            model_id="nemotron-cascade-2-30b-a3b-i1",
            label="Nemotron (ingest)",
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
