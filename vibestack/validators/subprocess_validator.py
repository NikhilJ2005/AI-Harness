"""Run the validation gates on the host, in a separate process.

This validator does not isolate the generated code: it runs with the same
interpreter and permissions as VibeStack itself. That is a deliberate trade for
speed, and it is the right choice for tests and continuous integration, where
the code under test is our own templates. Use the Docker validator for code that
should not be trusted.
"""

import os
import subprocess
import sys
from pathlib import Path

from vibestack.validation import ValidationGate, ValidationResult
from vibestack.validators.gate_output import GATE_RUNNER_PATH, parse_gate_output

DEFAULT_TIMEOUT_SECONDS = 600


class SubprocessValidator:
    """Runs the gates in a child process on the host."""

    def __init__(self, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds

    def describe(self) -> str:
        """Return a short description, for printing to the user."""
        return "subprocess (fast, no isolation)"

    def validate(self, project_directory: Path) -> ValidationResult:
        """Run every gate against the project and report the first failure."""
        # The child inherits our environment, with the project directory added
        # so that "app" resolves to the generated package.
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(project_directory)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"

        try:
            completed = subprocess.run(
                [sys.executable, str(GATE_RUNNER_PATH)],
                cwd=str(project_directory),
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                env=environment,
            )
        except subprocess.TimeoutExpired:
            return ValidationResult.failure(
                ValidationGate.BOOT,
                f"Validation timed out after {self._timeout_seconds} seconds.",
            )

        combined_output = completed.stdout + completed.stderr
        return parse_gate_output(combined_output, fallback_gate=ValidationGate.IMPORT)
