"""A wrapper over LiteLLM that returns validated objects and records what they cost."""

import threading

import instructor
import litellm

from vibestack.config import Settings
from vibestack.llm_protocol import ModelTier, ResponseModelT
from vibestack.usage import UsageRecord, purpose_for

# How to ask a model for structured output, strongest first. Tool calling is the
# most reliable but not every model supports it, so a refusal falls through to
# plain JSON and then to JSON wrapped in a markdown block.
MODE_CHAIN = ["tools", "json", "md_json"]

INSTRUCTOR_MODES = {
    "tools": instructor.Mode.TOOLS,
    "json": instructor.Mode.JSON,
    "md_json": instructor.Mode.MD_JSON,
}


def build_mode_chain(preferred: str) -> list[str]:
    """The preferred mode first, then the rest as fallbacks."""
    if preferred not in INSTRUCTOR_MODES:
        preferred = MODE_CHAIN[0]
    return [preferred] + [mode for mode in MODE_CHAIN if mode != preferred]


class LLMClient:
    """Calls models through LiteLLM and keeps a record of every call."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._clients: dict[str, instructor.Instructor] = {}

        # The review council fires five calls at once, so the usage list needs
        # a lock.
        self._usage_lock = threading.Lock()
        self._usage: list[UsageRecord] = []

    def _client_for_mode(self, mode_name: str) -> instructor.Instructor:
        if mode_name not in self._clients:
            self._clients[mode_name] = instructor.from_litellm(
                litellm.completion, mode=INSTRUCTOR_MODES[mode_name]
            )
        return self._clients[mode_name]

    def _fallback_chain(self, tier: ModelTier) -> list[str]:
        """The requested tier first, then the other models, de-duplicated."""
        candidates = [
            self._settings.model_for_tier(tier.value),
            self._settings.mid_model,
            self._settings.cheap_model,
            self._settings.premium_model,
        ]
        unique_models: list[str] = []
        for model_name in candidates:
            if model_name and model_name not in unique_models:
                unique_models.append(model_name)
        return unique_models

    def _record(self, purpose: str, tier: ModelTier, model: str, completion) -> None:
        """Store what a call cost. Never let accounting break a working call."""
        prompt_tokens = completion_tokens = 0
        cost = 0.0
        try:
            usage = getattr(completion, "usage", None)
            if usage is not None:
                prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                completion_tokens = getattr(usage, "completion_tokens", 0) or 0
            cost = litellm.completion_cost(completion_response=completion) or 0.0
        except Exception:
            # Free models and unknown providers often report no price at all.
            pass

        record = UsageRecord(
            purpose=purpose,
            tier=tier.value,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
        )
        with self._usage_lock:
            self._usage.append(record)

    def drain_usage(self) -> list[UsageRecord]:
        """Return everything recorded so far and clear it."""
        with self._usage_lock:
            records = list(self._usage)
            self._usage.clear()
        return records

    def structured_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModelT],
        tier: ModelTier = ModelTier.MID,
    ) -> ResponseModelT:
        """Tries every model, and every mode per model. Raises only if all fail."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        purpose = purpose_for(response_model)
        mode_chain = build_mode_chain(self._settings.instructor_mode)

        last_error: Exception | None = None
        for model_name in self._fallback_chain(tier):
            for mode_name in mode_chain:
                try:
                    result, completion = self._client_for_mode(
                        mode_name
                    ).chat.completions.create_with_completion(
                        model=model_name,
                        messages=messages,
                        response_model=response_model,
                        api_key=self._settings.openrouter_api_key,
                        timeout=self._settings.request_timeout_seconds,
                        max_retries=1,
                    )
                except Exception as error:
                    last_error = error
                    continue

                self._record(purpose, tier, model_name, completion)
                return result

        raise RuntimeError(
            f"Every model and mode failed to produce a valid {response_model.__name__}."
        ) from last_error
