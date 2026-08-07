"""Tests for configuration loading."""

from vibestack.config import Settings


def test_defaults_have_no_api_key():
    """Without an environment variable, there is no API key configured."""
    settings = Settings(_env_file=None)
    assert settings.has_api_key() is False


def test_has_api_key_true_when_set():
    """A non-empty key should be detected."""
    settings = Settings(_env_file=None, openrouter_api_key="sk-test-123")
    assert settings.has_api_key() is True


def test_model_tiers_have_defaults():
    """Each routing tier should have a default model configured."""
    settings = Settings(_env_file=None)
    assert settings.cheap_model
    assert settings.mid_model
    assert settings.premium_model
