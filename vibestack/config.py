"""Application configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration, read from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Credentials ----------------------------------------------------------
    openrouter_api_key: str = ""

    # Model routing tiers --------------------------------------------------
    # Cheap models handle routine work (parsing, classification); the premium
    # model is reserved for hard reasoning. Names use LiteLLM's OpenRouter
    # format: "openrouter/<provider>/<model>".
    cheap_model: str = "openrouter/deepseek/deepseek-chat"
    mid_model: str = "openrouter/openai/gpt-4o-mini"
    premium_model: str = "openrouter/anthropic/claude-3.5-sonnet"

    # Behaviour ------------------------------------------------------------
    request_timeout_seconds: int = 60

    def has_api_key(self) -> bool:
        return bool(self.openrouter_api_key.strip())
