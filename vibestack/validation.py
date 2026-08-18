"""The result of validating a generated project."""

from enum import Enum
from typing import Protocol

from pydantic import BaseModel

# Only the tail of a log is kept: tracebacks put the useful part last, and
# sending less text to the repair model keeps token costs down.
MAX_LOG_CHARACTERS = 4000


class ValidationGate(str, Enum):
    """The checks a generated project must pass, in the order they run."""

    BUILD = "build"  # the container image builds (Docker only)
    IMPORT = "import"  # every module imports without error
    BOOT = "boot"  # the app starts and answers a health check
    TESTS = "tests"  # the generated test suite passes


class ValidationResult(BaseModel):
    """Whether a project passed validation, and what went wrong if not."""

    passed: bool
    failed_gate: ValidationGate | None = None
    logs: str = ""

    @classmethod
    def success(cls) -> "ValidationResult":
        return cls(passed=True)

    @classmethod
    def failure(cls, gate: ValidationGate, logs: str) -> "ValidationResult":
        return cls(passed=False, failed_gate=gate, logs=trim_logs(logs))

    def summary(self) -> str:
        if self.passed:
            return "All validation gates passed."
        gate_name = self.failed_gate.value if self.failed_gate else "unknown"
        return f"Validation failed at the '{gate_name}' gate."


def trim_logs(logs: str) -> str:
    if len(logs) <= MAX_LOG_CHARACTERS:
        return logs
    return logs[-MAX_LOG_CHARACTERS:]


class Validator(Protocol):
    """Anything that can check whether a generated project works."""

    def validate(self, project_directory) -> ValidationResult:
        ...
