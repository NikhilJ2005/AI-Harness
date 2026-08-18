"""Run the validation gates on the host, in a separate process."""

import os
import subprocess
import sys
from pathlib import Path

from vibestack.validation import ValidationGate, ValidationResult
from vibestack.validators.gate_output import GATE_RUNNER_PATH, parse_gate_output

DEFAULT_TIMEOUT_SECONDS = 600

# Settings VibeStack reads for itself. A generated project reads some of the
# same names — DATABASE_URL and SECRET_KEY especially — so inheriting them would
# point the project under test at our database instead of its own, and it would
# fail for reasons that have nothing to do with the generated code.
HOST_ONLY_VARIABLES = (
    "DATABASE_URL",
    "SECRET_KEY",
    "ACCESS_TOKEN_EXPIRE_MINUTES",
    "OPENROUTER_API_KEY",
    "CHEAP_MODEL",
    "MID_MODEL",
    "PREMIUM_MODEL",
    "INSTRUCTOR_MODE",
    "REQUEST_TIMEOUT_SECONDS",
)


def build_child_environment(project_directory: Path) -> dict[str, str]:
    """The parent environment, minus anything that belongs to VibeStack."""
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in HOST_ONLY_VARIABLES
    }
    environment["PYTHONPATH"] = str(project_directory)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


class SubprocessValidator:
    """Runs the gates in a child process on the host."""

    def __init__(self, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds

    def describe(self) -> str:
        return "subprocess (fast, no isolation)"

    def validate(self, project_directory: Path) -> ValidationResult:
        environment = build_child_environment(project_directory)

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
