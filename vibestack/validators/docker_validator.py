"""Run the validation gates inside a container."""

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
        return "docker (isolated)"

    def validate(self, project_directory: Path) -> ValidationResult:
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
        """Returns a result only on failure, None when the build succeeded."""
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
        """Turns a timeout into an ordinary failure rather than an exception."""
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
        for tag in tags:
            subprocess.run(
                ["docker", "image", "rm", "--force", tag],
                capture_output=True,
                text=True,
            )
