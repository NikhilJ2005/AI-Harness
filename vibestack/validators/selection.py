"""Choosing which validator to use."""

from enum import Enum

from vibestack.validators.docker_validator import DockerValidator, docker_is_available
from vibestack.validators.subprocess_validator import SubprocessValidator


class SandboxKind(str, Enum):
    """How the user wants generated code to be validated."""

    AUTO = "auto"  # Docker when it is available, otherwise a subprocess
    DOCKER = "docker"
    SUBPROCESS = "subprocess"


def build_validator(kind: SandboxKind = SandboxKind.AUTO):
    """Return the validator to use.

    ``AUTO`` prefers Docker because it isolates the generated code and also
    checks the generated Dockerfile, but falls back to a subprocess so that
    validation still runs on machines without a Docker daemon.
    """
    if kind is SandboxKind.DOCKER:
        return DockerValidator()
    if kind is SandboxKind.SUBPROCESS:
        return SubprocessValidator()

    if docker_is_available():
        return DockerValidator()
    return SubprocessValidator()
