"""Measure how well VibeStack generates backends across many specifications.

Run it with:

    python -m vibestack.benchmark

Every specification in ``benchmarks/specs`` is generated into a temporary
directory and put through the validation gates. The result is a table of what
worked, what did not, and how long it took.

Because generation is deterministic, this benchmark needs no API key and gives
the same answer every time — which is what makes it a benchmark rather than an
anecdote. Supplying a key additionally exercises the self-healing loop, and the
report says which mode was used.
"""

import argparse
import json
import statistics
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from vibestack.agent import GenerationAgent
from vibestack.config import Settings
from vibestack.healing import validate_and_heal
from vibestack.llm_protocol import StructuredLLM
from vibestack.spec import ProjectSpec
from vibestack.validation import Validator
from vibestack.validators import SandboxKind, build_validator
from vibestack.workspace import write_workspace

DEFAULT_SPEC_DIRECTORY = Path("benchmarks/specs")
DEFAULT_REPORT_PATH = Path("benchmarks/results.json")


@dataclass
class CaseResult:
    """What happened for one specification."""

    name: str
    project_name: str
    generated: bool = False
    validated: bool = False
    file_count: int = 0
    ledger_entries: int = 0
    plan_notes: list[str] = field(default_factory=list)
    heal_attempts: int = 0
    failed_gate: str = ""
    duration_seconds: float = 0.0
    error: str = ""


@dataclass
class BenchmarkReport:
    """The outcome of a whole benchmark run."""

    healing_enabled: bool
    sandbox: str
    results: list[CaseResult] = field(default_factory=list)

    def case_count(self) -> int:
        return len(self.results)

    def validated_count(self) -> int:
        return sum(1 for result in self.results if result.validated)

    def success_rate(self) -> float:
        """Return the share of specifications that produced a working project."""
        if not self.results:
            return 0.0
        return self.validated_count() / len(self.results)

    def average_duration(self) -> float:
        if not self.results:
            return 0.0
        return statistics.mean(result.duration_seconds for result in self.results)

    def average_files(self) -> float:
        if not self.results:
            return 0.0
        return statistics.mean(result.file_count for result in self.results)

    def average_heal_attempts(self) -> float:
        if not self.results:
            return 0.0
        return statistics.mean(result.heal_attempts for result in self.results)


def load_specs(spec_directory: Path) -> list[tuple[str, ProjectSpec]]:
    """Read every specification file, in filename order."""
    cases: list[tuple[str, ProjectSpec]] = []
    for spec_path in sorted(spec_directory.glob("*.json")):
        spec = ProjectSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
        cases.append((spec_path.stem, spec))
    return cases


def run_case(
    name: str,
    spec: ProjectSpec,
    validator: Validator,
    llm: StructuredLLM | None,
) -> CaseResult:
    """Generate and validate one specification.

    Each case runs in its own temporary directory, so the cases cannot affect
    each other and nothing is left behind.
    """
    result = CaseResult(name=name, project_name=spec.project_name)
    started_at = time.monotonic()

    try:
        state = GenerationAgent().run(spec)
        result.generated = True
        result.file_count = len(state.generated_files)
        result.ledger_entries = len(state.ledger)
        result.plan_notes = [
            entry.rationale for entry in state.ledger if entry.stage == "plan"
        ]

        with tempfile.TemporaryDirectory(prefix="vibestack-benchmark-") as directory:
            project_directory = Path(directory)
            write_workspace(state, project_directory)

            validation = validate_and_heal(state, project_directory, validator, llm)
            result.validated = validation.passed
            result.heal_attempts = state.heal_attempts
            if validation.failed_gate is not None:
                result.failed_gate = validation.failed_gate.value

    except Exception as error:
        # A crash is a benchmark result, not a reason to abandon the run.
        result.error = f"{type(error).__name__}: {error}"

    result.duration_seconds = round(time.monotonic() - started_at, 2)
    return result


def run_benchmark(
    spec_directory: Path,
    sandbox: SandboxKind,
    llm: StructuredLLM | None,
    on_progress=None,
) -> BenchmarkReport:
    """Run every specification and collect the results."""
    validator = build_validator(sandbox)
    report = BenchmarkReport(
        healing_enabled=llm is not None,
        sandbox=validator.describe(),
    )

    for name, spec in load_specs(spec_directory):
        if on_progress is not None:
            on_progress(f"Running {name}...")

        case_result = run_case(name, spec, validator, llm)
        report.results.append(case_result)

        if on_progress is not None:
            on_progress(f"  {_describe(case_result)}")

    return report


def _describe(result: CaseResult) -> str:
    """Return a one-line description of a case result."""
    if result.error:
        return f"error: {result.error}"
    if result.validated:
        healed = f", healed {result.heal_attempts}x" if result.heal_attempts else ""
        return (
            f"passed ({result.file_count} files, "
            f"{result.duration_seconds}s{healed})"
        )
    return f"FAILED at the '{result.failed_gate or 'unknown'}' gate"


def format_markdown(report: BenchmarkReport) -> str:
    """Render the report as a markdown document."""
    lines = [
        "# Benchmark results",
        "",
        f"- Specifications: **{report.case_count()}**",
        f"- Passed every validation gate: **{report.validated_count()}"
        f"/{report.case_count()}** ({report.success_rate() * 100:.0f}%)",
        f"- Average generation and validation time: **{report.average_duration():.2f}s**",
        f"- Average files per project: **{report.average_files():.1f}**",
        f"- Average repair attempts: **{report.average_heal_attempts():.2f}**",
        f"- Sandbox: {report.sandbox}",
        f"- Self-healing: {'enabled' if report.healing_enabled else 'not exercised (no API key)'}",
        "",
        "| Specification | Files | Validated | Repairs | Time (s) | Notes |",
        "|---|---|---|---|---|---|",
    ]

    for result in report.results:
        verdict = "yes" if result.validated else "no"
        note = result.error or result.failed_gate or ""
        lines.append(
            f"| `{result.name}` | {result.file_count} | {verdict} | "
            f"{result.heal_attempts} | {result.duration_seconds} | {note} |"
        )

    plan_notes = _collect_plan_notes(report)
    if plan_notes:
        lines.extend(
            [
                "",
                "## Specification repairs",
                "",
                "Problems the planner found and fixed before generating, each",
                "recorded in the change ledger:",
                "",
            ]
        )
        for name, notes in plan_notes:
            for note in notes:
                lines.append(f"- `{name}`: {note}")

    return "\n".join(lines) + "\n"


def _collect_plan_notes(report: BenchmarkReport) -> list[tuple[str, list[str]]]:
    """Return the planning notes for cases that had any."""
    return [
        (result.name, result.plan_notes)
        for result in report.results
        if result.plan_notes
    ]


def build_argument_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="vibestack.benchmark",
        description="Measure generation success across many specifications.",
    )
    parser.add_argument(
        "--specs",
        default=str(DEFAULT_SPEC_DIRECTORY),
        help=f"Directory of specification files (default: {DEFAULT_SPEC_DIRECTORY}).",
    )
    parser.add_argument(
        "--out",
        default=str(DEFAULT_REPORT_PATH),
        help=f"Where to write the JSON report (default: {DEFAULT_REPORT_PATH}).",
    )
    parser.add_argument(
        "--markdown",
        metavar="PATH",
        help="Also write a markdown report to this path.",
    )
    parser.add_argument(
        "--sandbox",
        choices=[kind.value for kind in SandboxKind],
        default=SandboxKind.SUBPROCESS.value,
        help="How to validate (default: subprocess, for speed and repeatability).",
    )
    parser.add_argument(
        "--no-healing",
        action="store_true",
        help="Never call a model, even when an API key is configured.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark from the command line."""
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    spec_directory = Path(args.specs)
    if not spec_directory.is_dir():
        print(f"Error: no such directory: {spec_directory}", file=sys.stderr)
        return 1

    llm = None
    if not args.no_healing:
        settings = Settings()
        if settings.has_api_key():
            # Imported here so the benchmark runs without the model libraries
            # installed when no key is configured.
            from vibestack.llm_client import LLMClient

            llm = LLMClient(settings)

    report = run_benchmark(
        spec_directory,
        SandboxKind(args.sandbox),
        llm,
        on_progress=lambda message: print(message, file=sys.stderr),
    )

    report_path = Path(args.out)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")

    markdown = format_markdown(report)
    if args.markdown:
        markdown_path = Path(args.markdown)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(markdown, encoding="utf-8")

    print("\n" + markdown)
    print(f"JSON report written to {report_path}", file=sys.stderr)

    # A non-zero exit code when anything failed makes this usable in CI.
    return 0 if report.validated_count() == report.case_count() else 1


if __name__ == "__main__":
    raise SystemExit(main())
