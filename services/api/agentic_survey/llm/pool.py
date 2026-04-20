from dataclasses import dataclass, field
from enum import StrEnum
import os
from pathlib import Path
import re
from typing import Mapping

import yaml


class AgentRole(StrEnum):
    DESIGNER = "designer"
    INTERVIEWER = "interviewer"
    VALIDATOR = "validator"
    ANALYST = "analyst"
    EMBEDDINGS = "embeddings"


@dataclass(slots=True)
class EndpointConfig:
    name: str
    base_url: str
    model: str
    roles: set[AgentRole] = field(default_factory=set)


class EndpointPool:
    def __init__(
        self,
        registry_path: Path,
        variables: Mapping[str, str] | None = None,
    ) -> None:
        self.registry_path = registry_path
        self._session_pins: dict[str, str] = {}
        self._variables = dict(os.environ)
        if variables is not None:
            self._variables.update(variables)
        self._endpoints = self._load_registry()

    def _load_registry(self) -> dict[str, EndpointConfig]:
        raw = yaml.safe_load(self.registry_path.read_text()) or {}
        endpoints: dict[str, EndpointConfig] = {}
        for name, config in raw.get("endpoints", {}).items():
            endpoints[name] = EndpointConfig(
                name=name,
                base_url=self._interpolate_value(config["base_url"]),
                model=self._interpolate_value(config["model"]),
                roles={AgentRole(role) for role in config.get("roles", [])},
            )
        return endpoints

    def _interpolate_value(self, value: str) -> str:
        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in self._variables:
                raise KeyError(f"Missing interpolation variable: {key}")
            return self._variables[key]

        return re.sub(r"\$\{([A-Z0-9_]+)\}", replace, value)

    def pin_session(self, session_id: str, endpoint_name: str) -> None:
        if endpoint_name not in self._endpoints:
            raise KeyError(f"Unknown endpoint: {endpoint_name}")
        self._session_pins[session_id] = endpoint_name

    def get_endpoint(self, endpoint_name: str) -> EndpointConfig:
        if endpoint_name not in self._endpoints:
            raise KeyError(f"Unknown endpoint: {endpoint_name}")
        return self._endpoints[endpoint_name]

    def resolve_endpoint(self, role: AgentRole, session_id: str | None = None) -> EndpointConfig:
        if session_id and session_id in self._session_pins:
            return self._endpoints[self._session_pins[session_id]]

        for endpoint in self._endpoints.values():
            if role in endpoint.roles:
                return endpoint
        raise LookupError(f"No endpoint registered for role {role}")

    def to_litellm_model_list(self) -> list[dict]:
        role_aliases = {
            AgentRole.DESIGNER: "mira-chatter",
            AgentRole.INTERVIEWER: "mira-chatter",
            AgentRole.VALIDATOR: "validator",
            AgentRole.ANALYST: "analyst",
            AgentRole.EMBEDDINGS: "embeddings",
        }
        model_list: list[dict] = []
        seen_aliases: set[str] = set()

        for endpoint in self._endpoints.values():
            for role in sorted(endpoint.roles, key=lambda item: item.value):
                alias = role_aliases[role]
                if alias in seen_aliases:
                    continue
                params: dict[str, object] = {
                    "model": f"openai/{endpoint.model}",
                    "api_base": endpoint.base_url,
                }
                model_list.append({"model_name": alias, "litellm_params": params})
                seen_aliases.add(alias)

        scientific_endpoint = next(
            (
                endpoint
                for endpoint in self._endpoints.values()
                if AgentRole.ANALYST in endpoint.roles or AgentRole.VALIDATOR in endpoint.roles
            ),
            None,
        )
        if scientific_endpoint is not None and "mira-scientist" not in seen_aliases:
            model_list.append(
                {
                    "model_name": "mira-scientist",
                    "litellm_params": {
                        "model": f"openai/{scientific_endpoint.model}",
                        "api_base": scientific_endpoint.base_url,
                    },
                    "model_info": {
                        "supports_response_schema": True,
                    },
                }
            )

        return model_list
