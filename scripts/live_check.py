"""Run one real generation against OpenRouter and report what it cost.

    python scripts/live_check.py "a blog API with users, posts and JWT auth"

This is the script that either supports or kills the "under five cents per
generation" claim. Everything else in the test suite uses a stub client, so this
is the only place the model path is genuinely exercised.
"""

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from vibestack.config import Settings  # noqa: E402
from vibestack.llm_client import LLMClient  # noqa: E402
from vibestack.orchestrator import run_pipeline  # noqa: E402
from vibestack.stages.council import run_council  # noqa: E402
from vibestack.usage import collect_usage, summarise  # noqa: E402
from vibestack.validators import SandboxKind, build_validator  # noqa: E402

DEFAULT_PROMPT = "a blog API with users, posts, comments and JWT auth"


def report_usage(state) -> None:
    summary = summarise(state.usage)

    print("\n--- cost ---")
    if not state.usage:
        print("No model calls were recorded.")
        return

    for purpose, cost in sorted(summary.cost_by_purpose.items()):
        calls = summary.calls_by_purpose.get(purpose, 0)
        print(f"  {purpose:<8} {calls:>2} call(s)   ${cost:.6f}")

    print(
        f"\n  total    {summary.calls:>2} call(s)   ${summary.cost_usd:.6f}"
        f"   ({summary.prompt_tokens}+{summary.completion_tokens} tokens)"
    )

    if summary.cost_usd == 0:
        print("\n  Zero cost reported. Expected on free models, which publish no price.")
    elif summary.cost_usd < 0.05:
        print(f"\n  Under the $0.05 target, with ${0.05 - summary.cost_usd:.4f} to spare.")
    else:
        print(f"\n  OVER the $0.05 target by ${summary.cost_usd - 0.05:.4f}.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="?", default=DEFAULT_PROMPT)
    parser.add_argument("--no-review", action="store_true", help="Skip the review council.")
    parser.add_argument(
        "--sandbox",
        choices=[kind.value for kind in SandboxKind],
        default=SandboxKind.SUBPROCESS.value,
    )
    args = parser.parse_args()

    settings = Settings()
    if not settings.has_api_key():
        print("OPENROUTER_API_KEY is not set. Copy .env.example to .env first.")
        return 1

    llm = LLMClient(settings)
    print(f'Prompt: "{args.prompt}"')
    print(f"Models: cheap={settings.cheap_model}  mid={settings.mid_model}")
    print(f"        premium={settings.premium_model}\n")

    with tempfile.TemporaryDirectory(prefix="vibestack-live-") as directory:
        output_directory = Path(directory)
        state = run_pipeline(
            args.prompt,
            llm,
            output_directory,
            validator=build_validator(SandboxKind(args.sandbox)),
            on_progress=lambda message: print(f"  {message}"),
        )

        if not args.no_review:
            print("\nRunning the review council...")
            report = run_council(state, llm)
            collect_usage(state, llm)
            print(f"  {len(report.findings)} finding(s), {len(report.failed_lenses)} lens failure(s)")
            for finding in report.findings[:5]:
                print(f"    [{finding.severity.value}] {finding.lens.value}: {finding.summary}")

        print("\n--- result ---")
        print(f"  entities  : {len(state.spec.entities)}")
        print(f"  files     : {len(state.generated_files)}")
        print(f"  validated : {state.build_passed}")
        print(f"  repairs   : {state.heal_attempts}")
        if not state.build_passed and state.error_log:
            print(f"\n{state.error_log[:600]}")

        report_usage(state)

    return 0 if state.build_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
