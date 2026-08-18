"""Reading the gate runner's report out of a process's output."""

import json
from pathlib import Path

from vibestack.resources.gate_runner import RESULT_MARKER
from vibestack.validation import ValidationGate, ValidationResult

GATE_RUNNER_PATH = Path(__file__).parent.parent / "resources" / "gate_runner.py"


def parse_gate_output(process_output: str, fallback_gate: ValidationGate) -> ValidationResult:
    """A missing marker means the runner itself died, so the whole output is the log."""
    marker_line = ""
    for line in process_output.splitlines():
        if line.startswith(RESULT_MARKER):
            marker_line = line

    if not marker_line:
        return ValidationResult.failure(fallback_gate, process_output)

    payload = json.loads(marker_line[len(RESULT_MARKER) :])
    if payload["passed"]:
        return ValidationResult.success()

    return ValidationResult.failure(
        ValidationGate(payload["failed_gate"]),
        payload["logs"],
    )
