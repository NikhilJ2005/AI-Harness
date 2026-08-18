"""Runs the validation gates from inside a generated project.

This script is copied into the project under test and executed there, either on
the host or inside a container. It reports its findings as one JSON line on
standard output, prefixed with a marker so the caller can pick it out from any
other output the project produces.

It deliberately has no dependency on VibeStack itself, because it runs in the
generated project's environment, not ours.
"""

import importlib
import json
import subprocess
import sys
import traceback

RESULT_MARKER = "__VIBESTACK_RESULT__"
MAX_LOG_CHARACTERS = 4000


def run_import_gate() -> tuple[bool, str]:
    """Check that the application module imports without error."""
    try:
        importlib.import_module("app.main")
    except BaseException:
        # BaseException, not Exception: a bad module can raise SystemExit.
        return False, traceback.format_exc()
    return True, ""


def run_boot_gate() -> tuple[bool, str]:
    """Check that the application starts and answers its health check.

    Building a test client runs the application's startup, which is where table
    creation and router registration happen, so this catches far more than a
    plain import does.
    """
    try:
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)
        response = client.get("/health")
    except BaseException:
        return False, traceback.format_exc()

    if response.status_code != 200:
        return False, (
            f"The /health endpoint returned {response.status_code} "
            f"instead of 200. Body: {response.text}"
        )
    return True, ""


def run_tests_gate() -> tuple[bool, str]:
    """Run the project's own test suite."""
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return False, "The test suite timed out after 300 seconds."

    if completed.returncode != 0:
        return False, completed.stdout + completed.stderr
    return True, ""


def build_gate_list() -> list[tuple[str, object]]:
    """Return the gates in the order they must run.

    Cheapest and most fundamental first: there is no point running the test
    suite if the application cannot even be imported.
    """
    return [
        ("import", run_import_gate),
        ("boot", run_boot_gate),
        ("tests", run_tests_gate),
    ]


def main() -> int:
    """Run each gate, stopping at the first failure, and report the outcome."""
    # The project directory must be importable as "app".
    if "" not in sys.path:
        sys.path.insert(0, "")

    for gate_name, gate_function in build_gate_list():
        passed, logs = gate_function()
        if not passed:
            result = {
                "passed": False,
                "failed_gate": gate_name,
                "logs": logs[-MAX_LOG_CHARACTERS:],
            }
            print(RESULT_MARKER + json.dumps(result))
            return 0

    print(RESULT_MARKER + json.dumps({"passed": True, "failed_gate": None, "logs": ""}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
