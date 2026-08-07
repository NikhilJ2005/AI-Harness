"""Command-line entry point for VibeStack.

Two ways to run a generation:

* from a natural-language prompt, which uses the language model to build the
  specification first;
* from a specification file, which needs no API key and always produces the
  same output — useful for demos, tests, and offline work.
"""

import argparse
import sys
from pathlib import Path

from vibestack.config import Settings
from vibestack.llm_client import LLMClient
from vibestack.orchestrator import generate_from_spec, run_pipeline
from vibestack.spec import ProjectSpec
from vibestack.stages.parse import parse_prompt_to_spec
from vibestack.state import GenerationState

DEFAULT_OUTPUT_DIRECTORY = "generated-backend"


def _build_argument_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="vibestack",
        description="Generate a FastAPI backend from a natural-language description.",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        default="",
        help='A description of the backend, e.g. "a blog API with users and posts".',
    )
    parser.add_argument(
        "-o",
        "--out",
        default=DEFAULT_OUTPUT_DIRECTORY,
        help=f"Directory to write the project into (default: {DEFAULT_OUTPUT_DIRECTORY}).",
    )
    parser.add_argument(
        "--from-spec",
        metavar="PATH",
        help="Generate from a saved specification file instead of a prompt.",
    )
    parser.add_argument(
        "--spec-only",
        action="store_true",
        help="Print the specification as JSON without generating any files.",
    )
    return parser


def _report_results(state: GenerationState, output_directory: Path) -> None:
    """Print a short summary of what was generated."""
    file_count = len(state.generated_files)
    print(f"\nGenerated {file_count} files in {output_directory}")
    print("\nWhat was created and why:")
    for entry in state.ledger:
        print(f"  [{entry.stage}] {entry.file_path}")
        print(f"      {entry.rationale}")

    print("\nNext steps:")
    print(f"  cd {output_directory}")
    print("  docker compose up --build")


def _load_spec_from_file(path_text: str) -> ProjectSpec:
    """Read a specification from a JSON file."""
    spec_path = Path(path_text)
    return ProjectSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    """Run the VibeStack command-line interface.

    Returns a process exit code: 0 on success, non-zero on error.
    """
    parser = _build_argument_parser()
    args = parser.parse_args(argv)

    if not args.prompt and not args.from_spec:
        parser.error("provide a prompt, or use --from-spec to load a specification")

    output_directory = Path(args.out)

    # Generating from a saved specification needs no model access at all.
    if args.from_spec:
        spec = _load_spec_from_file(args.from_spec)
        if args.spec_only:
            print(spec.model_dump_json(indent=2))
            return 0

        print(f"Generating '{spec.project_name}' from {args.from_spec}", file=sys.stderr)
        state = generate_from_spec(spec, output_directory)
        _report_results(state, output_directory)
        return 0

    settings = Settings()
    if not settings.has_api_key():
        print(
            "Error: OPENROUTER_API_KEY is not set.\n"
            "Copy .env.example to .env and add your OpenRouter API key,\n"
            "or use --from-spec to generate from a saved specification.",
            file=sys.stderr,
        )
        return 1

    llm = LLMClient(settings)
    print(f'Parsing prompt: "{args.prompt}"', file=sys.stderr)

    if args.spec_only:
        spec = parse_prompt_to_spec(args.prompt, llm)
        print(spec.model_dump_json(indent=2))
        return 0

    state = run_pipeline(args.prompt, llm, output_directory)
    _report_results(state, output_directory)
    return 0
