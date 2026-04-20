from functools import lru_cache
from pathlib import Path
from typing import Literal

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
    default_interviewer_endpoint: str = "mini"
    repository: Literal["memory", "surreal"] = "memory"
    litellm_config_path: str = "agentic_survey/llm/litellm_config.yaml"

    surreal_url: str = "ws://localhost:8400"
    surreal_ns: str = "agentic_survey"
    surreal_db: str = "prod"
    surreal_user: str = "root"
    surreal_pass: str = "root"
    export_dir: str = "./campaigns"

    searxng_url: str = "http://searxng:8080"

    mini_endpoint_url: str = "http://mini:8080/v1"
    mini_model: str = "gemma-4-26B-A4B-it-Q4_K_M"
    dynamo_endpoint_url: str = "http://dynamo:1234/v1"
    dynamo_model: str = "nemotron-cascade-2-30b-a3b-i1"
    embedding_model: str = "text-embedding-nomic-embed-text-v2-moe"
    llm_enabled: bool = False
    llm_timeout_seconds: float = 60.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
