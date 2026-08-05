from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Everything is overridable by environment variable."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "job-tracker-api"
    environment: str = "local"
    api_prefix: str = "/api/v1"

    # Postgres in every deployed environment; SQLite keeps local dev and CI dependency-free.
    database_url: str = "sqlite+pysqlite:///./job_tracker.db"

    # When unset the app runs without Redis: ingestion executes in-process and SSE is
    # served from an in-memory hub. Both are fine for single-process local development.
    redis_url: str | None = None

    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60 * 24 * 14

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # Ingestion
    fetch_timeout_seconds: float = 15.0
    fetch_user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36 job-tracker/0.1"
    )
    fetch_cache_ttl_seconds: int = 60 * 60 * 24
    max_description_chars: int = 200_000

    # Tier 4 — LLM structuring. Disabled unless a key is present.
    anthropic_api_key: str | None = None
    llm_model: str = "claude-opus-5"
    llm_max_input_chars: int = 32_000
    llm_monthly_call_cap: int = 500

    # Staleness thresholds surfaced to the board (days).
    stale_warn_days: int = 14
    stale_dim_days: int = 30

    # Reminders. The in-app and SSE paths always work; email needs a provider, so it
    # stays off until one is configured (see src/services/notify.py).
    reminder_email_enabled: bool = False
    reminder_sweep_hour_utc: int = 13  # ~8am ET, when a follow-up is worth seeing

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
