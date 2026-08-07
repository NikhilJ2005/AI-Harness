"""Run the validation gates inside a container.

This is the validator to use for code you do not trust. It gives the generated
project its own filesystem and process space, denies it network access while the
gates run, and caps the CPU, memory, and process count it can consume.

It also validates one thing the subprocess validator cannot: building the image
exercises the generated Dockerfile and its dependency list, so a broken
Dockerfile or an invented package is caught here rather than by the user.

Note on the isolation boundary: containers share the host kernel, so this is a
strong boundary but not a complete one. Hardening it further (gVisor, or a
microVM such as Firecracker) is future work.
"""

import shutil
import subprocess
from pathlib import Path

from vibestack.validation import ValidationGate, ValidationResult
from vibestack.validators.gate_output import GATE_RUNNER_PATH, parse_gate_output

DEFAULT_TIMEOUT_SECONDS = 900

# The check image adds the test tools, which the runtime image does not need.
CHECK_DOCKERFILE_NAME = "Dockerfile.vibestack-check"
CHECK_DOCKERFILE_TEMPLATE = """
FROM {base_image}
USER root
RUN pip install --no-cache-dir pytest httpx
"""

# Limits applied while the gates run, so a runaway project cannot exhaust the host.
CONTAINER_LIMITS = [
    "--network", "none",
    "--memory", "1g",
    "--cpus", "2",
    "--pids-limit", "256",
]


def docker_is_available() -> bool:
    """Return True when a usable Docker daemon is reachable."""
    if shutil.which("docker") is None:
        return False

    try:
        completed = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False

    return completed.returncode == 0


class DockerValidator:
    """Builds the generated image and runs the gates inside a container."""

    def __init__(self, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds

    def describe(self) -> str:
        """Return a short description, for printing to the user."""
        return "docker (isolated)"

    def validate(self, project_directory: Path) -> ValidationResult:
        """Build the image, then run every gate inside a container."""
        base_tag = f"vibestack-app-{project_directory.name}".lower()
        check_tag = f"{base_tag}-check"

        build_result = self._build_image(project_directory, base_tag)
        if build_result is not None:
            return build_result

        check_build_result = self._build_check_image(project_directory, base_tag, check_tag)
        if check_build_result is not None:
            return check_build_result

        try:
            return self._run_gates(check_tag)
        finally:
            self._remove_images([check_tag, base_tag])

    def _build_image(self, project_directory: Path, tag: str) -> ValidationResult | None:
        """Build the project's own Dockerfile. Returns a result only on failure."""
        completed = self._run_command(
            ["docker", "build", "--tag", tag, "."],
            working_directory=project_directory,
        )
        if completed.returncode != 0:
            return ValidationResult.failure(
                ValidationGate.BUILD, completed.stdout + completed.stderr
            )
        return None

    def _build_check_image(
        self, project_directory: Path, base_tag: str, check_tag: str
    ) -> ValidationResult | None:
        """Add the test tools on top of the built image."""
        dockerfile_path = project_directory / CHECK_DOCKERFILE_NAME
        dockerfile_path.write_text(
            CHECK_DOCKERFILE_TEMPLATE.format(base_image=base_tag),
            encoding="utf-8",
        )

        try:
            completed = self._run_command(
                [
                    "docker", "build",
                    "--tag", check_tag,
                    "--file", CHECK_DOCKERFILE_NAME,
                    ".",
                ],
                working_directory=project_directory,
            )
        finally:
            # The temporary Dockerfile must never be left in the user's output.
            dockerfile_path.unlink(missing_ok=True)

        if completed.returncode != 0:
            return ValidationResult.failure(
                ValidationGate.BUILD, completed.stdout + completed.stderr
            )
        return None

    def _run_gates(self, image_tag: str) -> ValidationResult:
        """Run the gate runner inside a container built from the image."""
        command = [
            "docker", "run", "--rm",
            *CONTAINER_LIMITS,
            "--volume", f"{GATE_RUNNER_PATH}:/tmp/gate_runner.py:ro",
            "--workdir", "/app",
            image_tag,
            "python", "/tmp/gate_runner.py",
        ]
        completed = self._run_command(command, working_directory=None)
        combined_output = completed.stdout + completed.stderr
        return parse_gate_output(combined_output, fallback_gate=ValidationGate.IMPORT)

    def _run_command(
        self, command: list[str], working_directory: Path | None
    ) -> subprocess.CompletedProcess:
        """Run a docker command, turning a timeout into an ordinary failure."""
        try:
            return subprocess.run(
                command,
                cwd=str(working_directory) if working_directory else None,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(
                args=command,
                returncode=1,
                stdout="",
                stderr=f"Docker command timed out after {self._timeout_seconds} seconds.",
            )

    def _remove_images(self, tags: list[str]) -> None:
        """Delete the images we built, ignoring any failure to do so."""
        for tag in tags:
            subprocess.run(
                ["docker", "image", "rm", "--force", tag],
                capture_output=True,
                text=True,
            )
