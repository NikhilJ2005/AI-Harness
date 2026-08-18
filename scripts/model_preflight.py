"""Check that every configured model exists and honours structured output.

    python scripts/model_preflight.py

Worth running before a demo. OpenRouter's free tier changes without notice — the
free Qwen and Llama endpoints were withdrawn in August 2026 — so a model that
worked last week can be gone today. This turns that into a line of output
instead of a broken demo.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic import BaseModel  # noqa: E402

from vibestack.config import Settings  # noqa: E402
from vibestack.llm_client import LLMClient, build_mode_chain  # noqa: E402
from vibestack.llm_protocol import ModelTier  # noqa: E402

SYSTEM_PROMPT = "You answer with structured data only."
USER_PROMPT = "The city of Kochi is in the Indian state of Kerala. Fill in the fields."


class Answer(BaseModel):
    """Deliberately tiny, so a preflight costs almost nothing."""

    city: str
    state: str


def check_tier(tier: ModelTier, settings: Settings) -> bool:
    model = settings.model_for_tier(tier.value)
    print(f"\n{tier.value:<8} {model}")

    client = LLMClient(settings)
    started = time.monotonic()
    try:
        answer = client.structured_completion(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=USER_PROMPT,
            response_model=Answer,
            tier=tier,
        )
    except Exception as error:
        print(f"         FAILED  {type(error).__name__}: {error}")
        return False

    elapsed = time.monotonic() - started
    records = client.drain_usage()
    used = records[0] if records else None

    print(f"         ok      {elapsed:.1f}s  -> city={answer.city!r} state={answer.state!r}")
    if used:
        # The model that answered may not be the one asked for: the fallback
        # chain will have moved on if the first choice was unavailable.
        served_by = "as configured" if used.model == model else f"SERVED BY {used.model}"
        print(
            f"         {used.prompt_tokens}+{used.completion_tokens} tokens, "
            f"${used.cost_usd:.6f}  ({served_by})"
        )
    return True


def main() -> int:
    settings = Settings()
    if not settings.has_api_key():
        print("OPENROUTER_API_KEY is not set. Copy .env.example to .env first.")
        return 1

    print("Preflight: one small structured request per tier.")
    print(f"Mode order: {' -> '.join(build_mode_chain(settings.instructor_mode))}")

    results = {tier: check_tier(tier, settings) for tier in ModelTier}

    working = sum(1 for ok in results.values() if ok)
    print(f"\n{working}/{len(results)} tiers usable.")

    if working == 0:
        print("Nothing is usable. Check the key, then the model names on openrouter.ai.")
    elif working < len(results):
        print("Some tiers failed. Generation will still work through the fallback chain.")

    return 0 if working == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
