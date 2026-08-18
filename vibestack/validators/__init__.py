"""Ways of running the validation gates against a generated project.

Two are provided. The Docker validator gives real isolation and also proves the
generated Dockerfile works, so it is the default when a daemon is available. The
subprocess validator runs the same gates on the host: it needs no daemon and is
much faster, which makes it the right choice for tests and continuous
integration.
"""

from vibestack.validators.docker_validator import DockerValidator
from vibestack.validators.selection import SandboxKind, build_validator, docker_is_available
from vibestack.validators.subprocess_validator import SubprocessValidator

__all__ = [
    "DockerValidator",
    "SandboxKind",
    "SubprocessValidator",
    "build_validator",
    "docker_is_available",
]
