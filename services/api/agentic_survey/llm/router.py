from __future__ import annotations

import argparse
import asyncio
import inspect
import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping

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


def _openrouter_fallback_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """OpenRouter fallback is on iff the flag is true AND the api key is set.

    Reads from the live process env so YAML interpolation and this gate read the
    same source. Settings sync env vars in `get_litellm_router` before construction.
    """
    source: Mapping[str, str] = environ if environ is not None else os.environ
    flag = source.get("SURVEY_OPENROUTER_FALLBACK_ENABLED", "false").strip().lower()
    if flag not in {"1", "true", "yes", "on"}:
        return False
    return bool(source.get("SURVEY_OPENROUTER_API_KEY", "").strip())


def _requires_env_satisfied(
    requires_env: Any,
    environ: Mapping[str, str],
) -> bool:
    """True when every var in ``requires_env`` resolves to a non-empty string."""
    if requires_env is None:
        return True
    if not isinstance(requires_env, list):
        raise LiteLLMRouterError(
            f"_requires_env must be a list of env-var names, got {type(requires_env).__name__}"
        )
    for var in requires_env:
        if not isinstance(var, str) or not var:
            raise LiteLLMRouterError(
                f"_requires_env entries must be non-empty strings, got {var!r}"
            )
        if not environ.get(var, "").strip():
            return False
    return True


def load_filtered_model_list(
    config_path: Path | str,
    environ: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Load a litellm model_list with env-presence gating and per-alias dedup.

    Each row may carry two metadata keys consumed only by this loader:

    * ``_requires_env``: list of SURVEY_* var names that must all resolve to
      non-empty strings for the row to survive. Phase 1 (mini+dynamo) keeps the
      mini and dynamo rows; phase 5 (only OpenRouter) drops both because both
      URL vars are empty.
    * ``_openrouter_fallback``: row stays only when ``_openrouter_fallback_enabled``
      reports True (flag truthy AND api key present). Existing rows for
      validator/analyst/ingest already use this gate; mira-chatter and
      mira-scientist gain matching rows.

    Surviving rows are deduplicated by ``model_name``, keeping the first match —
    which is the highest priority since YAML order is preserved. The metadata
    keys are stripped before return so the result is ready for ``litellm.Router``.
    """
    source: Mapping[str, str] = environ if environ is not None else os.environ
    raw_path = Path(config_path).expanduser()
    if not raw_path.is_absolute():
        raw_path = _resolve_path(str(raw_path))
    if not raw_path.exists():
        raise LiteLLMRouterError(f"LiteLLM config not found: {raw_path}")
    raw = yaml.safe_load(raw_path.read_text()) or {}

    openrouter_enabled = _openrouter_fallback_enabled(source)
    survivors: list[dict[str, Any]] = []
    for entry in raw.get("model_list", []) or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("_openrouter_fallback") and not openrouter_enabled:
            continue
        if not _requires_env_satisfied(entry.get("_requires_env"), source):
            continue
        survivors.append(entry)

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in survivors:
        name = entry.get("model_name")
        if not isinstance(name, str) or not name:
            continue
        if name in seen:
            continue
        seen.add(name)
        cleaned = {k: v for k, v in entry.items() if k not in {"_requires_env", "_openrouter_fallback"}}
        # Allow missing for OpenRouter rows so a half-configured fallback fails
        # at call time, not at boot. Local rows fail strictly because their
        # _requires_env gate already proved every var is set.
        allow_missing = bool(entry.get("_openrouter_fallback"))
        deduped.append(_interpolate(cleaned, allow_missing=allow_missing, environ=source))
    return deduped


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


def _interpolate(
    value: Any,
    *,
    allow_missing: bool = False,
    environ: Mapping[str, str] | None = None,
) -> Any:
    source: Mapping[str, str] = environ if environ is not None else os.environ
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in source:
                if allow_missing:
                    return ""
                raise LiteLLMRouterError(f"Missing interpolation variable: {key}")
            return source[key]

        return _ENV_PATTERN.sub(replace, value)
    if isinstance(value, list):
        return [_interpolate(item, allow_missing=allow_missing, environ=source) for item in value]
    if isinstance(value, dict):
        return {
            key: _interpolate(item, allow_missing=allow_missing, environ=source)
            for key, item in value.items()
        }
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
        raw["model_list"] = load_filtered_model_list(self._config_path)
        if "router_settings" in raw:
            raw["router_settings"] = _interpolate(raw["router_settings"])
        return raw

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

        # The reasoning resolver mirrors `reasoning_mode` onto `reasoning_effort`
        # so the same prepared request works on either OpenRouter (which honors
        # it) or LM Studio / ollama (which ignore it). LiteLLM's strict mode
        # raises UnsupportedParamsError when the param isn't recognized for the
        # destination model. drop_params=True is the documented LiteLLM way to
        # silently strip unsupported params per-backend instead of failing.
        litellm.drop_params = True

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
    os.environ.setdefault("SURVEY_CHATTER_ENDPOINT_URL", settings.chatter_endpoint_url)
    os.environ.setdefault("SURVEY_CHATTER_MODEL", settings.chatter_model)
    os.environ.setdefault("SURVEY_SCIENTIST_ENDPOINT_URL", settings.scientist_endpoint_url)
    os.environ.setdefault("SURVEY_SCIENTIST_MODEL", settings.scientist_model)
    os.environ.setdefault("SURVEY_EMBEDDING_MODEL", settings.embedding_model)
    # Embedding endpoint falls back to scientist URL when the operator has
    # not set an explicit value, so the historical single-backend deploy
    # keeps working without a config change. setdefault keeps explicit shell
    # exports authoritative.
    os.environ.setdefault(
        "SURVEY_EMBEDDING_ENDPOINT_URL",
        settings.embedding_endpoint_url.strip() or settings.scientist_endpoint_url,
    )
    # LiteLLM's OpenAI-compat client requires an api_key field even when talking
    # to a local server that ignores it (LM Studio, llama.cpp, Ollama). Reuse
    # the same placeholder used by the chat endpoints.
    os.environ.setdefault("SURVEY_EMBEDDING_API_KEY", os.environ.get("OPENAI_API_KEY", "lm-studio"))
    # OpenRouter fallback. setdefault keeps explicit shell exports authoritative.
    os.environ.setdefault("SURVEY_OPENROUTER_API_KEY", settings.openrouter_api_key)
    os.environ.setdefault("SURVEY_OPENROUTER_BASE_URL", settings.openrouter_base_url)
    os.environ.setdefault("SURVEY_OPENROUTER_SCIENTIST_MODEL", settings.openrouter_scientist_model)
    os.environ.setdefault(
        "SURVEY_OPENROUTER_FALLBACK_ENABLED",
        "true" if settings.openrouter_fallback_enabled else "false",
    )
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
