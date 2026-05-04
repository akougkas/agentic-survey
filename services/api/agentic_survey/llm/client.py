from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from agentic_survey.llm.callbacks import failure_callback, success_callback
from agentic_survey.llm.catalog import (
    AgentRole as CatalogRole,
    CatalogResolution,
    resolve as resolve_catalog,
)
from agentic_survey.llm.pool import AgentRole, EndpointConfig, EndpointPool
from agentic_survey.llm.reasoning import (
    apply_reasoning_settings,
    repair_completion_tokens,
    set_lmstudio_thinking,
)
from agentic_survey.llm.router import LiteLLMRouter, LiteLLMRouterError, get_litellm_router
from agentic_survey.repository import Campaign, InMemoryRepository, get_repository

logger = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    """Raised when the upstream inference endpoint is unreachable or returns an error."""


@dataclass(slots=True)
class ChatMessage:
    role: str
    content: str


@dataclass(slots=True)
class ChatCompletion:
    content: str
    reasoning_content: str = ""


def _as_openai_messages(messages: Iterable[ChatMessage]) -> list[dict[str, str]]:
    return [{"role": message.role, "content": message.content} for message in messages]


def _extract_message_content(response: object) -> ChatCompletion:
    usage = _extract_value(response, "usage")
    _ = usage
    choices = _extract_value(response, "choices") or []
    if not choices:
        raise LLMUnavailable(f"malformed llm response: {response!r}")
    message = _extract_value(choices[0], "message") or {}
    content = str(_extract_value(message, "content") or "").strip()
    reasoning_content = str(_extract_value(message, "reasoning_content") or "").strip()
    if not content:
        tool_calls = _extract_value(message, "tool_calls") or []
        if tool_calls:
            first = tool_calls[0]
            fn = _extract_value(first, "function") or {}
            arguments = str(_extract_value(fn, "arguments") or "").strip()
            if arguments:
                content = arguments
    return ChatCompletion(content=content, reasoning_content=reasoning_content)


def _extract_value(obj: object, key: str) -> object | None:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _model_alias_for_role(role: AgentRole) -> str:
    aliases = {
        AgentRole.DESIGNER: "mira-chatter",
        AgentRole.INTERVIEWER: "mira-chatter",
        AgentRole.VALIDATOR: "validator",
        AgentRole.ANALYST: "analyst",
        AgentRole.EMBEDDINGS: "embeddings",
    }
    return aliases[role]


def _alias_for_catalog_role(catalog_role: CatalogRole) -> str:
    aliases: dict[str, str] = {
        "chatter": "mira-chatter",
        "scientist": "mira-scientist",
        "validator": "validator",
        "analyst": "analyst",
        "ingest": "ingest",
        "embedding": "embeddings",
    }
    return aliases[catalog_role]




class LLMClient:
    def __init__(
        self,
        pool: EndpointPool,
        router: LiteLLMRouter,
        repository: InMemoryRepository,
        *,
        enabled: bool = True,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._pool = pool
        self._router = router
        self._repository = repository
        self._enabled = enabled
        self._timeout_seconds = timeout_seconds

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def pool(self) -> EndpointPool:
        return self._pool

    def resolve(
        self,
        role: AgentRole,
        session_id: str | None = None,
        *,
        campaign: Campaign | None = None,
        catalog_role: CatalogRole | None = None,
    ) -> EndpointConfig:
        if campaign is None and catalog_role is None:
            return self._pool.resolve_endpoint(role, session_id=session_id)
        resolved = self._resolve_catalog_route(role, campaign=campaign, catalog_role=catalog_role)
        return EndpointConfig(
            name=resolved.endpoint,
            base_url=resolved.api_base,
            model=resolved.model_id,
        )

    def resolve_endpoint(self, role: AgentRole, session_id: str | None = None) -> EndpointConfig:
        return self._pool.resolve_endpoint(role, session_id=session_id)

    async def chat(
        self,
        role: AgentRole,
        messages: Iterable[ChatMessage],
        *,
        session_id: str | None = None,
        campaign: Campaign | None = None,
        catalog_role: CatalogRole | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        response_format: dict | None = None,
        extra_body: dict | None = None,
    ) -> ChatCompletion:
        if not self._enabled:
            raise LLMUnavailable("llm client disabled (SURVEY_LLM_ENABLED=false)")
        messages_list = _as_openai_messages(messages)
        endpoint: EndpointConfig
        model_name: str
        metadata_extra: dict[str, object] | None = None
        resolution: CatalogResolution | None = None

        if campaign is not None or catalog_role is not None:
            resolution = self._resolve_catalog_route(role, campaign=campaign, catalog_role=catalog_role)
            endpoint = EndpointConfig(
                name=resolution.endpoint,
                base_url=resolution.api_base,
                model=resolution.model_id,
            )
            model_name = _alias_for_catalog_role(resolution.role)
            metadata_extra = {
                "catalog_id": resolution.catalog_id,
                "catalog_role": resolution.role,
                "router_alias": model_name,
                "route_source": resolution.source,
                "reasoning_mode": resolution.reasoning_mode,
                "reasoning_kwarg": resolution.reasoning_kwarg,
                "reasoning_budget_tokens": resolution.reasoning_budget_tokens,
            }
            logger.warning(
                "llm route surface=%s catalog_role=%s source=%s using catalog=%s alias=%s endpoint=%s model=%s reasoning=%s/%s",
                role.value,
                resolution.role,
                resolution.source,
                resolution.catalog_id or "env-fallback",
                model_name,
                resolution.endpoint,
                resolution.model_id,
                resolution.reasoning_kwarg,
                resolution.reasoning_mode,
            )
        else:
            endpoint = self._pool.resolve_endpoint(role, session_id=session_id)
            model_name = _model_alias_for_role(role)

        completion = await self._acompletion(
            role=role,
            session_id=session_id,
            endpoint=endpoint,
            model_name=model_name,
            messages=messages_list,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            extra_body=extra_body,
            metadata_extra=metadata_extra,
            resolution=resolution,
            disable_reasoning=False,
        )
        if completion.content:
            return completion

        logger.warning("llm %s returned empty content; retrying with repair nudge", endpoint.name)
        repair_messages = list(messages_list)
        repair_messages.append(
            {
                "role": "system",
                "content": (
                    "Do not deliberate. Output the final answer immediately. "
                    "No reasoning, no preamble, under 90 words."
                ),
            }
        )
        retry_completion = await self._acompletion(
            role=role,
            session_id=session_id,
            endpoint=endpoint,
            model_name=model_name,
            messages=repair_messages,
            temperature=max(0.0, temperature - 0.2),
            max_tokens=repair_completion_tokens(),
            response_format=response_format,
            extra_body=extra_body,
            metadata_extra=metadata_extra,
            resolution=resolution,
            disable_reasoning=True,
        )
        if retry_completion.content:
            return retry_completion
        raise LLMUnavailable(f"llm {endpoint.name} produced empty content after retry")

    async def _acompletion(
        self,
        *,
        role: AgentRole,
        session_id: str | None,
        endpoint: EndpointConfig,
        model_name: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: dict | None,
        extra_body: dict | None,
        metadata_extra: dict[str, object] | None,
        resolution: CatalogResolution | None = None,
        disable_reasoning: bool = False,
    ) -> ChatCompletion:
        metadata: dict[str, object] = {
            "surface": role.value,
            "session_id": session_id,
            "endpoint_name": endpoint.name,
            "endpoint_model": endpoint.model,
        }
        if metadata_extra:
            metadata.update(metadata_extra)
        request: dict[str, object] = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "metadata": metadata,
        }
        if response_format is not None:
            request["response_format"] = response_format
        if extra_body:
            request["extra_body"] = dict(extra_body)
        if disable_reasoning:
            set_lmstudio_thinking(request, enabled=False)
        elif resolution is not None:
            apply_reasoning_settings(resolution, request)
        start_time = datetime.now(tz=UTC)
        try:
            response = await self._router.acompletion(**request)
        except LiteLLMRouterError as exc:
            failure_callback(request, exc, start_time, datetime.now(tz=UTC))
            raise LLMUnavailable(f"llm request to {endpoint.name} failed: {exc}") from exc
        except Exception as exc:
            failure_callback(request, exc, start_time, datetime.now(tz=UTC))
            raise LLMUnavailable(f"llm request to {endpoint.name} failed: {exc}") from exc
        success_callback(request, response, start_time, datetime.now(tz=UTC))
        return _extract_message_content(response)

    def _resolve_catalog_route(
        self,
        role: AgentRole,
        *,
        campaign: Campaign | None,
        catalog_role: CatalogRole | None,
    ):
        resolved_role = _catalog_role_for_request(role, catalog_role)
        return resolve_catalog(
            resolved_role,
            campaign_models=None if campaign is None else campaign.agent_models,
            catalog=self._repository.list_catalog(),
            pool=self._pool,
        )


def _catalog_role_for_request(role: AgentRole, override: CatalogRole | None) -> CatalogRole:
    if override is not None:
        return override
    mapping: dict[AgentRole, CatalogRole] = {
        AgentRole.DESIGNER: "chatter",
        AgentRole.INTERVIEWER: "chatter",
        AgentRole.VALIDATOR: "validator",
        AgentRole.ANALYST: "analyst",
        AgentRole.EMBEDDINGS: "embedding",
    }
    return mapping[role]


@lru_cache(maxsize=1)
def get_endpoint_pool() -> EndpointPool:
    from agentic_survey.config import get_settings

    settings = get_settings()
    registry = Path(__file__).parent / "models.yaml"
    variables = {
        "SURVEY_MINI_ENDPOINT_URL": settings.mini_endpoint_url,
        "SURVEY_MINI_MODEL": settings.mini_model,
        "SURVEY_DYNAMO_ENDPOINT_URL": settings.dynamo_endpoint_url,
        "SURVEY_DYNAMO_MODEL": settings.dynamo_model,
    }
    return EndpointPool(registry, variables=variables)


@lru_cache(maxsize=1)
def get_llm_client() -> LLMClient:
    from agentic_survey.config import get_settings

    settings = get_settings()
    router = get_litellm_router()
    return LLMClient(
        get_endpoint_pool(),
        router,
        get_repository(),
        enabled=settings.llm_enabled,
        timeout_seconds=settings.llm_timeout_seconds,
    )
