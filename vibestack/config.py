"""Configuration, read from the environment or a local .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict

# OpenRouter's free tier changes without notice — the free Qwen and Llama
# endpoints were withdrawn in August 2026 — so these are starting points, not
# guarantees. Run scripts/model_preflight.py before relying on them.
DEFAULT_FREE_MODEL = "openrouter/openai/gpt-oss-120b:free"
DEFAULT_PAID_MODEL = "openrouter/anthropic/claude-3.5-sonnet"


class Settings(BaseSettings):
    """Configuration, read from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openrouter_api_key: str = ""

    # Model tiers. Names use LiteLLM's OpenRouter form:
    # "openrouter/<provider>/<model>".
    cheap_model: str = DEFAULT_FREE_MODEL
    mid_model: str = DEFAULT_FREE_MODEL
    # Repair is the hard reasoning step, so the premium tier defaults to a paid
    # model. It is also what the fallback chain lands on when a free endpoint is
    # withdrawn, which is the whole point of having one.
    premium_model: str = DEFAULT_PAID_MODEL

    # How instructor should ask for structured output. "tools" is strongest but
    # needs function calling; "json" and "md_json" work on models without it.
    # The client falls back through the others if the configured one is refused.
    instructor_mode: str = "tools"

    request_timeout_seconds: int = 60

    # SQLite locally, Postgres in production. The same code serves both.
    database_url: str = "sqlite:///./vibestack.db"

    # Signs the access tokens. Must be set to something private before deploying.
    secret_key: str = "change-me-before-deploying"
    access_token_expire_minutes: int = 60 * 24

    def resolved_database_url(self) -> str:
        """Normalise the scheme Railway hands out.

        Railway supplies DATABASE_URL as "postgresql://", but SQLAlchemy 2 with
        psycopg 3 wants "postgresql+psycopg://". Rewriting it here means the
        platform's spelling never has to be correct.
        """
        url = self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url

    def has_api_key(self) -> bool:
        return bool(self.openrouter_api_key.strip())

    def model_for_tier(self, tier: str) -> str:
        if tier == "cheap":
            return self.cheap_model
        if tier == "premium":
            return self.premium_model
        return self.mid_model
