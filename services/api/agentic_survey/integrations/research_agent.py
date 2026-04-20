from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

ResearchScope = Literal["shallow", "standard", "deep"]

NULL_PROVIDER = "null"


class ResearchJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ResearchJobHandle(BaseModel):
    provider: str
    job_id: str
    campaign_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchAgentResult(BaseModel):
    sources: list[dict[str, Any]] = Field(default_factory=list)
    summary: str = ""
    confidence: float = 0.0
    rationale: str = ""


@runtime_checkable
class ResearchAgentHook(Protocol):
    async def dispatch(
        self,
        *,
        query: str,
        scope: ResearchScope = "standard",
        depth: int = 3,
    ) -> ResearchJobHandle: ...

    async def status(self, handle: ResearchJobHandle) -> ResearchJobStatus: ...

    async def fetch(self, handle: ResearchJobHandle) -> ResearchAgentResult: ...


class NullResearchAgent:
    """Default hook used when no research provider is configured.

    dispatch returns a typed handle, status always reports completed, and fetch
    returns an empty result whose rationale explains the missing adapter. Real
    adapters (OpenAI Deep Research, Perplexity, Exa, local agents) land
    post-v1 behind the same Protocol.
    """

    provider_name: str = NULL_PROVIDER

    async def dispatch(
        self,
        *,
        query: str,
        scope: ResearchScope = "standard",
        depth: int = 3,
    ) -> ResearchJobHandle:
        return ResearchJobHandle(
            provider=self.provider_name,
            job_id="null",
            metadata={"query": query, "scope": scope, "depth": depth},
        )

    async def status(self, handle: ResearchJobHandle) -> ResearchJobStatus:
        return ResearchJobStatus.COMPLETED

    async def fetch(self, handle: ResearchJobHandle) -> ResearchAgentResult:
        return ResearchAgentResult(rationale="No research agent configured")


def resolve_research_agent(
    provider: str | None,
    config: dict[str, Any] | None = None,
) -> ResearchAgentHook:
    """Resolve a research hook provider string to a live adapter.

    Only the null provider ships today; any other provider string raises so
    deployments fail loud rather than silently fall back to a no-op.
    """
    if provider is None or provider == NULL_PROVIDER:
        return NullResearchAgent()
    raise NotImplementedError(
        f"Research agent provider '{provider}' is not implemented yet. "
        "Only 'null' ships in v1; adapters land post-v1."
    )
