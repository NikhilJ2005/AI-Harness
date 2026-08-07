"""Application configuration.

All settings are read from environment variables (or a local ``.env`` file) so
that secrets like the API key never live in the source tree. See
``.env.example`` for the full list of supported variables.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for VibeStack.

    Field names map directly to environment variables (case-insensitive), so the
    field ``openrouter_api_key`` is filled from ``OPENROUTER_API_KEY``.
    """

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
        """Return True when an OpenRouter API key has been configured."""
        return bool(self.openrouter_api_key.strip())
