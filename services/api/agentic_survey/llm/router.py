from __future__ import annotations

import argparse
import asyncio
import inspect
import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger(__name__)

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")
_MODULE_ANCESTORS = Path(__file__).resolve().parents
_API_ROOT = _MODULE_ANCESTORS[2] if len(_MODULE_ANCESTORS) > 2 else Path.cwd()
# _REPO_ROOT is used for dev-tree path resolution; in containers (where the
# package sits at /app/agentic_survey) that ancestor is truncated, so fall
# back to _API_ROOT.
_REPO_ROOT = _MODULE_ANCESTORS[4] if len(_MODULE_ANCESTORS) > 4 else _API_ROOT


class LiteLLMRouterError(RuntimeError):
    """Raised when LiteLLM router initialization or invocation fails."""


def _resolve_path(raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate

    candidates = [
        Path.cwd() / candidate,
        _API_ROOT / candidate,
        _REPO_ROOT / candidate,
    ]
    for resolved in candidates:
        if resolved.exists():
            return resolved
    return candidates[0]


def _interpolate(value: Any) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in os.environ:
                raise LiteLLMRouterError(f"Missing interpolation variable: {key}")
            return os.environ[key]

        return _ENV_PATTERN.sub(replace, value)
    if isinstance(value, list):
        return [_interpolate(item) for item in value]
    if isinstance(value, dict):
        return {key: _interpolate(item) for key, item in value.items()}
    return value


def _extract_chunk_text(chunk: object) -> str:
    if isinstance(chunk, dict):
        choices = chunk.get("choices") or []
    else:
        choices = getattr(chunk, "choices", None) or []
    if not choices:
        return ""
    delta = choices[0].get("delta") if isinstance(choices[0], dict) else getattr(choices[0], "delta", None)
    if delta is None:
        return ""
    if isinstance(delta, dict):
        return str(delta.get("content") or "")
    return str(getattr(delta, "content", "") or "")


class LiteLLMRouter:
    def __init__(self, config_path: str) -> None:
        self._config_path = _resolve_path(config_path)
        self._success_callbacks: list[Callable[..., Any]] = []
        self._failure_callbacks: list[Callable[..., Any]] = []
        self._router = self._build_router()

    def _load_config(self) -> dict[str, Any]:
        if not self._config_path.exists():
            raise LiteLLMRouterError(f"LiteLLM config not found: {self._config_path}")
        raw = yaml.safe_load(self._config_path.read_text()) or {}
        return _interpolate(raw)

    def _install_callbacks(self, litellm_module: Any) -> None:
        litellm_module.success_callback = list(self._success_callbacks)
        litellm_module.failure_callback = list(self._failure_callbacks)
        if hasattr(litellm_module, "async_success_callback"):
            litellm_module.async_success_callback = list(self._success_callbacks)

    def _build_router(self) -> Any:
        try:
            import litellm
            from litellm import Router
        except ImportError as exc:
            raise LiteLLMRouterError("litellm is not installed") from exc

        self._install_callbacks(litellm)
        config = self._load_config()
        router_settings = config.get("router_settings", {})
        kwargs: dict[str, Any] = {"model_list": config.get("model_list", [])}
        signature = inspect.signature(Router.__init__)
        accepted = set(signature.parameters)

        if "routing_strategy" in accepted and "routing_strategy" in router_settings:
            kwargs["routing_strategy"] = router_settings["routing_strategy"]
        if "fallbacks" in accepted and "fallbacks" in router_settings:
            kwargs["fallbacks"] = router_settings["fallbacks"]
        if "cooldown_time" in accepted and "cooldown_time" in router_settings:
            kwargs["cooldown_time"] = router_settings["cooldown_time"]
        retry_policy = router_settings.get("retry_policy", {})
        if "num_retries" in accepted and "MaxRetries" in retry_policy:
            kwargs["num_retries"] = retry_policy["MaxRetries"]

        try:
            return Router(**kwargs)
        except Exception as exc:
            raise LiteLLMRouterError(f"failed to initialize LiteLLM router: {exc}") from exc

    def register_success_callback(self, callback: Callable[..., Any]) -> None:
        if callback not in self._success_callbacks:
            self._success_callbacks.append(callback)
            self._install_callbacks(__import__("litellm"))

    def register_failure_callback(self, callback: Callable[..., Any]) -> None:
        if callback not in self._failure_callbacks:
            self._failure_callbacks.append(callback)
            self._install_callbacks(__import__("litellm"))

    async def acompletion(self, **kwargs: Any) -> Any:
        try:
            return await self._router.acompletion(**kwargs)
        except Exception as exc:
            raise LiteLLMRouterError(str(exc)) from exc

    async def aembedding(self, **kwargs: Any) -> Any:
        try:
            return await self._router.aembedding(**kwargs)
        except Exception as exc:
            raise LiteLLMRouterError(str(exc)) from exc


@lru_cache(maxsize=1)
def get_litellm_router() -> LiteLLMRouter:
    from agentic_survey.config import get_settings

    settings = get_settings()
    os.environ.setdefault("SURVEY_MINI_ENDPOINT_URL", settings.mini_endpoint_url)
    os.environ.setdefault("SURVEY_MINI_MODEL", settings.mini_model)
    os.environ.setdefault("SURVEY_DYNAMO_ENDPOINT_URL", settings.dynamo_endpoint_url)
    os.environ.setdefault("SURVEY_DYNAMO_MODEL", settings.dynamo_model)
    os.environ.setdefault("SURVEY_EMBEDDING_MODEL", settings.embedding_model)
    return LiteLLMRouter(settings.litellm_config_path)


async def _run_smoke(model_name: str) -> int:
    from agentic_survey.config import get_settings

    settings = get_settings()
    if not settings.llm_enabled:
        raise LiteLLMRouterError("SURVEY_LLM_ENABLED must be true for the smoke test")

    router = get_litellm_router()
    stream = await router.acompletion(
        model=model_name,
        messages=[
            {
                "role": "system",
                "content": "Reply with exactly one short sentence confirming the path is live.",
            },
            {
                "role": "user",
                "content": "Smoke test the M1 LiteLLM router path.",
            },
        ],
        metadata={
            "surface": "designer",
            "session_id": "m1-smoke",
            "brain": "A",
        },
        stream=True,
    )
    emitted = False
    async for chunk in stream:
        text = _extract_chunk_text(chunk)
        if not text:
            continue
        emitted = True
        print(text, end="", flush=True)
    if emitted:
        print()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="LiteLLM router helper")
    parser.add_argument("--smoke", metavar="MODEL", help="Run a live smoke test against a configured model")
    args = parser.parse_args()
    if args.smoke:
        return asyncio.run(_run_smoke(args.smoke))
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
