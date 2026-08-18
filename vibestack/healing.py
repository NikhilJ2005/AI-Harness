"""The self-healing loop: validate, diagnose, repair, and try again."""

from collections.abc import Callable
from pathlib import Path

from vibestack.checkpoint import save_checkpoint
from vibestack.llm_protocol import StructuredLLM
from vibestack.stages.reflect import FilePatch, classify_build_error, propose_patch
from vibestack.state import GenerationState
from vibestack.validation import ValidationResult, Validator

# The circuit breaker. After this many repair attempts the loop stops and
# reports, however tempting one more try might be.
MAX_HEAL_ATTEMPTS = 3

# Called with progress messages so this module never prints directly.
ProgressCallback = Callable[[str], None]


def _report(on_progress: ProgressCallback | None, message: str) -> None:
    if on_progress is not None:
        on_progress(message)


def apply_patch(
    state: GenerationState, project_directory: Path, patch: FilePatch, reason: str
) -> None:
    """Writes to both state and disk: state feeds the next repair, disk feeds the next validation."""
    state.generated_files[patch.file_path] = patch.new_content

    destination = project_directory / patch.file_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(patch.new_content, encoding="utf-8")

    state.record_change(
        stage="self-heal",
        file_path=patch.file_path,
        rationale=f"{reason}: {patch.explanation}",
    )


def build_diagnostic(state: GenerationState, result: ValidationResult) -> str:
    category = classify_build_error(result.logs)
    gate_name = result.failed_gate.value if result.failed_gate else "unknown"

    return (
        f"{result.summary()}\n"
        f"Diagnosis: {category.value}\n"
        f"Repair attempts: {state.heal_attempts} of {MAX_HEAL_ATTEMPTS}\n"
        f"Failing gate: {gate_name}\n\n"
        f"Error log:\n{result.logs}"
    )


def validate_and_heal(
    state: GenerationState,
    project_directory: Path,
    validator: Validator,
    llm: StructuredLLM | None = None,
    on_progress: ProgressCallback | None = None,
) -> ValidationResult:
    """Validate the project, repairing it until it passes or the breaker trips.

    Args:
        state: The run's shared state; updated in place as repairs are applied.
        project_directory: Where the generated project was written.
        validator: How to run the gates (Docker or a subprocess).
        llm: Used to propose repairs. Without one, the project is validated and
            the result reported, but nothing is fixed.
        on_progress: Optional callback for progress messages.

    Returns:
        The final validation result. ``state.build_passed`` and
        ``state.error_log`` are updated to match.
    """
    attempt = 0

    while True:
        _report(on_progress, f"Validating ({validator.describe()})...")
        result = validator.validate(project_directory)

        if result.passed:
            state.build_passed = True
            state.error_log = ""
            _report(on_progress, "All validation gates passed.")
            return result

        category = classify_build_error(result.logs)
        _report(
            on_progress,
            f"{result.summary()} Diagnosis: {category.value}.",
        )

        if llm is None:
            _report(on_progress, "No model configured, so no repair was attempted.")
            break

        if attempt >= MAX_HEAL_ATTEMPTS:
            # The circuit breaker. Stopping here is the point: repeated failure
            # means the model is not converging, and further attempts only cost
            # tokens.
            _report(
                on_progress,
                f"Circuit breaker: stopping after {MAX_HEAL_ATTEMPTS} repair attempts.",
            )
            break

        attempt += 1
        _report(on_progress, f"Repair attempt {attempt} of {MAX_HEAL_ATTEMPTS}...")

        patch = propose_patch(state, result, llm)
        if patch is None:
            _report(on_progress, "No usable repair was proposed.")
            break

        apply_patch(state, project_directory, patch, reason=category.value)
        state.heal_attempts = attempt
        save_checkpoint(state, project_directory)
        _report(on_progress, f"Patched {patch.file_path}: {patch.explanation}")

    state.build_passed = False
    state.error_log = build_diagnostic(state, result)
    return result
