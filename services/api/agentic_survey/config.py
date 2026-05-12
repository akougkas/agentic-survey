from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_file_candidates() -> tuple[str, ...]:
    """Walk from cwd up to the git root, collecting every .env along the way.

    Pydantic Settings loads the list in order, so later (repo-root) values
    override earlier (per-service) ones. Stops at the first directory that
    holds a `.git` entry so we do not read arbitrary files from $HOME.
    """
    seen: list[str] = []
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        seen.append(str(candidate / ".env"))
        if (candidate / ".git").exists():
            break
    return tuple(seen)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SURVEY_",
        env_file=_env_file_candidates(),
        extra="ignore",
    )

    app_name: str = "Agentic Survey"
    environment: str = "development"
    public_base_url: str = ""
    frontend_origin: str = "http://127.0.0.1:5270"
    product_bundle_dir: str = ""

    admin_password: str = "change-me"
    admin_session_cookie_name: str = "survey_admin_session"
    admin_session_ttl_hours: int = 12
    participant_session_cookie_name: str = "survey_participant_session"
    participant_session_ttl_hours: int = 72
    freshness_default_cron: str = "0 3 * * *"
    default_interviewer_endpoint: str = "chatter"
    repository: Literal["memory", "surreal"] = "memory"
    litellm_config_path: str = "agentic_survey/llm/litellm_config.yaml"

    surreal_url: str = "ws://localhost:8400"
    surreal_ns: str = "agentic_survey"
    surreal_db: str = "prod"
    surreal_user: str = "root"
    surreal_pass: str = "root"
    export_dir: str = "./campaigns"

    searxng_url: str = "http://searxng:8080"

    # Web search (M3) -----------------------------------------------------
    # Design-time only. SearXNG primary when ``searxng_url`` is set; the
    # ``ddgs`` package provides fallback. Interview surface never calls web.
    web_search_top_k: int = 10

    # Ingestion worker (M2) -----------------------------------------------
    freshness_poll_seconds: int = 30
    ingest_min_chars: int = 500
    ingest_crawl4ai: bool = True
    ingest_http_timeout_seconds: float = 30.0
    ingest_crawl4ai_timeout_seconds: float = 60.0

    # Brain A — the conversationalist. Mira's voice. High-temperature, fast,
    # reasoning is always off because the participant sees this stream live.
    chatter_endpoint_url: str = "http://localhost:8080/v1"
    chatter_model: str = "AgenticQwen-30B-A3B-i1-Q4_K_M"
    chatter_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    # Brain B + validator + analyst + ingest. The analytical brain that plans,
    # validates, and uses tools. Lower temperature keeps tool selection focused.
    # ``scientist_supports_reasoning`` clamps reasoning_mode to "off" when the
    # deployed model does not actually have a thinking mode (Gemma, Qwen3-base,
    # AgenticQwen tool-tune). When False, the catalog forces enable_thinking=
    # false so the model does not burn per-turn budget on stream-of-consciousness.
    # Set to True only when the deployed model genuinely supports thinking
    # (Nemotron OMNI, Qwen3-Thinking, etc.).
    scientist_endpoint_url: str = "http://localhost:8080/v1"
    scientist_model: str = "AgenticQwen-30B-A3B-i1-Q4_K_M"
    scientist_temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    scientist_supports_reasoning: bool = False
    scientist_context_window_tokens: int = Field(default=200_000, ge=1)
    embedding_model: str = "text-embedding-nomic-embed-text-v2-moe"
    # Where embedding requests go. Empty falls back to scientist_endpoint_url
    # so the historical "embeddings on the analytical backend" path keeps
    # working unchanged. Set this to a separate Ollama (or whatever) endpoint
    # when the embedding model is served somewhere different from the chat/
    # reasoning model.
    embedding_endpoint_url: str = ""
    llm_enabled: bool = False
    llm_timeout_seconds: float = 60.0
    # Brain A's per-stream cap. Default 4096 absorbs LM Studio's reasoning
    # leakage on Nemotron OMNI when ``enable_thinking=false`` is ignored by
    # the chat-template; the model still emits EOS after the natural visible
    # reply so the cap is a safety bound, not a target length.
    llm_visible_reply_max_tokens: int = Field(default=4096, ge=1)
    llm_repair_completion_tokens: int = Field(default=1024, ge=1)
    llm_reasoning_budget_tokens: int = Field(default=8192, ge=1)
    llm_reasoning_final_response_tokens: int = Field(default=4096, ge=1)
    llm_preplan_reasoning_budget_tokens: int = Field(default=1024, ge=1)

    # OpenRouter fallback for scientist-served roles. Empty key + flag=False
    # keeps the router on the local backend only.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_scientist_model: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
    openrouter_fallback_enabled: bool = False

    # Operator override for retrieval mode at the binding layer. Empty string
    # means "respect the caller" (Brain B chooses hybrid/bm25/vector per its
    # prompt). A non-empty value forces every search_knowledge call into the
    # named mode regardless of what Brain B requested. Use "bm25" when the
    # embedding endpoint is offline so retrieval keeps working.
    retrieval_force_mode: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
