"""Tests for the benchmark runner."""

from pathlib import Path

import pytest

from vibestack.benchmark import (
    BenchmarkReport,
    CaseResult,
    format_markdown,
    load_specs,
    run_benchmark,
)
from vibestack.validation import ValidationGate, ValidationResult
from vibestack.validators import SandboxKind

# Resolved from this file rather than the working directory, so the tests pass
# no matter where pytest is started from.
SPEC_DIRECTORY = Path(__file__).parent.parent / "benchmarks" / "specs"


def test_the_shipped_specs_all_load():
    """Every benchmark specification must be valid, or the suite is worthless."""
    cases = load_specs(SPEC_DIRECTORY)

    assert len(cases) >= 10
    for name, spec in cases:
        assert spec.project_name, f"{name} has no project name"
        assert spec.entities, f"{name} has no entities"


def test_specs_run_in_a_stable_order():
    """Filename order keeps reports comparable between runs."""
    names = [name for name, _ in load_specs(SPEC_DIRECTORY)]

    assert names == sorted(names)


def _report_with(results: list[CaseResult]) -> BenchmarkReport:
    return BenchmarkReport(healing_enabled=False, sandbox="test", results=results)


def test_summary_statistics():
    """The headline numbers should be computed from the case results."""
    report = _report_with(
        [
            CaseResult(
                name="a",
                project_name="a",
                generated=True,
                validated=True,
                file_count=20,
                duration_seconds=2.0,
                heal_attempts=1,
            ),
            CaseResult(
                name="b",
                project_name="b",
                generated=True,
                validated=False,
                file_count=10,
                duration_seconds=4.0,
                failed_gate="import",
            ),
        ]
    )

    assert report.case_count() == 2
    assert report.validated_count() == 1
    assert report.success_rate() == 0.5
    assert report.average_duration() == 3.0
    assert report.average_files() == 15.0
    assert report.average_heal_attempts() == 0.5


def test_empty_report_does_not_divide_by_zero():
    report = _report_with([])

    assert report.success_rate() == 0.0
    assert report.average_duration() == 0.0


def test_markdown_report_shows_results_and_repairs():
    """The report must be readable on its own."""
    report = _report_with(
        [
            CaseResult(
                name="case_one",
                project_name="one",
                generated=True,
                validated=True,
                file_count=22,
                duration_seconds=2.5,
                plan_notes=["Added an 'id' primary key to Ticket."],
            )
        ]
    )

    markdown = format_markdown(report)

    assert "100%" in markdown
    assert "`case_one`" in markdown
    assert "Added an 'id' primary key to Ticket." in markdown
    assert "not exercised" in markdown  # healing was disabled


class AlwaysPassingValidator:
    """Reports success without running anything."""

    def describe(self) -> str:
        return "stub"

    def validate(self, project_directory) -> ValidationResult:
        # The project should actually have been written out before we are called.
        assert (project_directory / "app" / "main.py").is_file()
        return ValidationResult.success()


class AlwaysFailingValidator:
    """Reports a failure without running anything."""

    def describe(self) -> str:
        return "stub"

    def validate(self, project_directory) -> ValidationResult:
        return ValidationResult.failure(ValidationGate.IMPORT, "NameError: nope")


def test_run_benchmark_records_a_pass(tmp_path, monkeypatch):
    """A passing run should be reported as validated."""
    monkeypatch.setattr(
        "vibestack.benchmark.build_validator", lambda kind: AlwaysPassingValidator()
    )

    report = run_benchmark(SPEC_DIRECTORY, SandboxKind.SUBPROCESS, llm=None)

    assert report.case_count() >= 10
    assert report.success_rate() == 1.0
    for result in report.results:
        assert result.generated is True
        assert result.file_count > 0
        assert result.ledger_entries >= result.file_count


def test_run_benchmark_records_a_failure(monkeypatch):
    """A failing gate should be recorded rather than raised."""
    monkeypatch.setattr(
        "vibestack.benchmark.build_validator", lambda kind: AlwaysFailingValidator()
    )

    report = run_benchmark(SPEC_DIRECTORY, SandboxKind.SUBPROCESS, llm=None)

    assert report.validated_count() == 0
    assert all(result.failed_gate == "import" for result in report.results)


@pytest.mark.slow
def test_every_shipped_spec_really_generates_and_validates():
    """The headline claim: every benchmark specification produces a working project.

    This runs the real validation gates, so it is the slowest test in the suite
    and the one that would catch a regression in generation.
    """
    pytest.importorskip("fastapi", reason="the generated projects need FastAPI to run")

    report = run_benchmark(SPEC_DIRECTORY, SandboxKind.SUBPROCESS, llm=None)

    failures = [result.name for result in report.results if not result.validated]
    assert not failures, f"these specifications failed to validate: {failures}"
