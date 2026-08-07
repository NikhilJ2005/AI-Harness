"""Tests for validation results, gate output parsing, and checkpoints."""

from vibestack.checkpoint import checkpoint_path, load_checkpoint, save_checkpoint
from vibestack.resources.gate_runner import RESULT_MARKER
from vibestack.spec import Entity, EntityField, FieldType, ProjectSpec
from vibestack.state import GenerationState
from vibestack.validation import (
    MAX_LOG_CHARACTERS,
    ValidationGate,
    ValidationResult,
    trim_logs,
)
from vibestack.validators.gate_output import parse_gate_output
from vibestack.validators.selection import SandboxKind, build_validator


def test_success_result_has_no_failing_gate():
    result = ValidationResult.success()

    assert result.passed is True
    assert result.failed_gate is None
    assert result.summary() == "All validation gates passed."


def test_failure_result_names_the_gate():
    result = ValidationResult.failure(ValidationGate.BOOT, "it did not start")

    assert result.passed is False
    assert result.failed_gate is ValidationGate.BOOT
    assert "boot" in result.summary()


def test_trim_logs_keeps_the_end_where_the_error_is():
    """Tracebacks put the cause last, so the tail is the part worth keeping."""
    logs = ("filler " * 2000) + "NameError: name 'Text' is not defined"

    trimmed = trim_logs(logs)

    assert len(trimmed) == MAX_LOG_CHARACTERS
    assert trimmed.endswith("NameError: name 'Text' is not defined")


def test_short_logs_are_left_alone():
    assert trim_logs("a short log") == "a short log"


def test_parse_gate_output_reads_a_success_marker():
    output = f'noise\n{RESULT_MARKER}{{"passed": true, "failed_gate": null, "logs": ""}}'

    result = parse_gate_output(output, ValidationGate.IMPORT)

    assert result.passed is True


def test_parse_gate_output_reads_a_failure_marker():
    payload = '{"passed": false, "failed_gate": "tests", "logs": "assert 1 == 2"}'
    output = f"pytest noise\n{RESULT_MARKER}{payload}"

    result = parse_gate_output(output, ValidationGate.IMPORT)

    assert result.passed is False
    assert result.failed_gate is ValidationGate.TESTS
    assert "assert 1 == 2" in result.logs


def test_missing_marker_is_treated_as_a_failure():
    """If the runner never reported, something went badly wrong."""
    result = parse_gate_output("Segmentation fault", ValidationGate.IMPORT)

    assert result.passed is False
    assert result.failed_gate is ValidationGate.IMPORT
    assert "Segmentation fault" in result.logs


def test_explicit_sandbox_choices_are_honoured():
    assert build_validator(SandboxKind.SUBPROCESS).describe().startswith("subprocess")
    assert build_validator(SandboxKind.DOCKER).describe().startswith("docker")


def _example_state() -> GenerationState:
    spec = ProjectSpec(
        project_name="demo",
        description="",
        entities=[
            Entity(name="Note", fields=[EntityField(name="id", type=FieldType.INTEGER)])
        ],
    )
    state = GenerationState(spec=spec)
    state.generated_files["app/main.py"] = "# code\n"
    state.heal_attempts = 2
    return state


def test_checkpoint_round_trip(tmp_path):
    """A saved state should reload exactly as it was."""
    state = _example_state()

    save_checkpoint(state, tmp_path)
    restored = load_checkpoint(tmp_path)

    assert restored == state


def test_checkpoint_is_written_beside_the_project(tmp_path):
    """Checkpoints live in a dot directory so they do not clutter the output."""
    save_checkpoint(_example_state(), tmp_path)

    assert checkpoint_path(tmp_path).is_file()
    assert checkpoint_path(tmp_path).parent.name == ".vibestack"


def test_loading_without_a_checkpoint_returns_none(tmp_path):
    assert load_checkpoint(tmp_path) is None
