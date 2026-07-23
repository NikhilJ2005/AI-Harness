"""Command-line entry point for VibeStack.

Phase 0 exposes a single command: given a natural-language prompt, parse it into
a ``ProjectSpec`` and print the result as JSON. Later phases will extend this to
generate, validate, and package a full backend.
"""

import argparse
import sys

from vibestack.config import Settings
from vibestack.llm_client import LLMClient
from vibestack.stages.parse import parse_prompt_to_spec


def _build_argument_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="vibestack",
        description="Turn a natural-language description into a backend spec.",
    )
    parser.add_argument(
        "prompt",
        help='A description of the backend, e.g. "a blog API with users and posts".',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the VibeStack command-line interface.

    Returns a process exit code: 0 on success, non-zero on error.
    """
    parser = _build_argument_parser()
    args = parser.parse_args(argv)

    settings = Settings()
    if not settings.has_api_key():
        print(
            "Error: OPENROUTER_API_KEY is not set.\n"
            "Copy .env.example to .env and add your OpenRouter API key.",
            file=sys.stderr,
        )
        return 1

    llm = LLMClient(settings)

    # Progress messages go to stderr so that stdout carries only the spec JSON,
    # which keeps the output easy to pipe into a file or another program.
    print(f'Parsing prompt: "{args.prompt}"', file=sys.stderr)
    spec = parse_prompt_to_spec(args.prompt, llm)

    print(spec.model_dump_json(indent=2))
    return 0
