"""A thin wrapper over LiteLLM that returns validated Pydantic objects.

Two responsibilities live here:

1. Structured output — we use ``instructor`` so the model is constrained to
   return JSON matching a Pydantic model, with automatic re-asks on invalid
   output. Callers get a typed object, never a raw string.
2. Model fallback — each request targets a tier (cheap/mid/premium). If the
   chosen model fails, we try the remaining configured models in order before
   giving up, so a single provider hiccup does not fail the whole run.
"""

import instructor
import litellm

from vibestack.config import Settings
from vibestack.llm_protocol import ModelTier, ResponseModelT


class LLMClient:
    """Calls language models through LiteLLM and returns typed results."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # ``instructor`` patches LiteLLM's ``completion`` function so we can pass
        # a ``response_model`` and get back a validated Pydantic object.
        self._structured = instructor.from_litellm(litellm.completion)

    def _model_for_tier(self, tier: ModelTier) -> str:
        """Return the configured model name for a routing tier."""
        if tier is ModelTier.CHEAP:
            return self._settings.cheap_model
        if tier is ModelTier.PREMIUM:
            return self._settings.premium_model
        return self._settings.mid_model

    def _fallback_chain(self, tier: ModelTier) -> list[str]:
        """Return the model to try first, followed by fallbacks.

        We start with the requested tier's model, then fall back to the other
        configured models. Duplicates are removed while preserving order.
        """
        candidates = [
            self._model_for_tier(tier),
            self._settings.mid_model,
            self._settings.cheap_model,
            self._settings.premium_model,
        ]
        unique_models: list[str] = []
        for model_name in candidates:
            if model_name and model_name not in unique_models:
                unique_models.append(model_name)
        return unique_models

    def structured_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModelT],
        tier: ModelTier = ModelTier.MID,
    ) -> ResponseModelT:
        """Send the prompts to the model and return a validated object.

        Tries each model in the fallback chain until one succeeds. Raises a
        ``RuntimeError`` only if every model fails.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        last_error: Exception | None = None
        for model_name in self._fallback_chain(tier):
            try:
                return self._structured.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    response_model=response_model,
                    api_key=self._settings.openrouter_api_key,
                    timeout=self._settings.request_timeout_seconds,
                    max_retries=2,
                )
            except Exception as error:
                # Deliberately broad: any failure means we try the next model.
                last_error = error

        raise RuntimeError(
            "Every model in the fallback chain failed to produce a valid "
            f"{response_model.__name__}."
        ) from last_error
