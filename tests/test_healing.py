"""Tests for the self-healing loop.

The loop is driven by fake validators and a fake repair model, so every path —
success, repair, circuit breaker — can be checked exactly and without network
access.
"""

from vibestack.checkpoint import load_checkpoint
from vibestack.healing import MAX_HEAL_ATTEMPTS, validate_and_heal
from vibestack.spec import Entity, EntityField, FieldType, ProjectSpec
from vibestack.stages.reflect import FilePatch
from vibestack.state import GenerationState
from vibestack.validation import ValidationGate, ValidationResult

FAILING_LOG = 'File "app/main.py", line 1\nNameError: name \'Text\' is not defined'


class ScriptedValidator:
    """Returns a prepared sequence of results, one per call."""

    def __init__(self, results: list[ValidationResult]) -> None:
        self._results = list(results)
        self.call_count = 0

    def describe(self) -> str:
        return "scripted"

    def validate(self, project_directory) -> ValidationResult:
        self.call_count += 1
        if self._results:
            return self._results.pop(0)
        # Once the script runs out, keep failing.
        return ValidationResult.failure(ValidationGate.IMPORT, FAILING_LOG)


class CountingRepairLLM:
    """Proposes the same patch every time and counts how often it is asked."""

    def __init__(self) -> None:
        self.call_count = 0

    def structured_completion(self, system_prompt, user_prompt, response_model, tier=None):
        self.call_count += 1
        return FilePatch(
            file_path="app/main.py",
            new_content="# repaired\n",
            explanation="added the missing import",
        )


def build_state() -> GenerationState:
    """Build a state with a single generated file."""
    spec = ProjectSpec(
        project_name="demo",
        description="",
        entities=[
            Entity(name="Note", fields=[EntityField(name="id", type=FieldType.INTEGER)])
        ],
    )
    state = GenerationState(spec=spec)
    state.generated_files["app/main.py"] = "# original\n"
    return state


def test_passing_project_is_not_repaired(tmp_path):
    """A project that already works must not be touched."""
    state = build_state()
    validator = ScriptedValidator([ValidationResult.success()])
    llm = CountingRepairLLM()

    result = validate_and_heal(state, tmp_path, validator, llm)

    assert result.passed is True
    assert state.build_passed is True
    assert state.heal_attempts == 0
    assert llm.call_count == 0
    assert state.error_log == ""


def test_failure_is_repaired_and_revalidated(tmp_path):
    """One failure, one repair, then success."""
    state = build_state()
    validator = ScriptedValidator(
        [
            ValidationResult.failure(ValidationGate.IMPORT, FAILING_LOG),
            ValidationResult.success(),
        ]
    )
    llm = CountingRepairLLM()

    result = validate_and_heal(state, tmp_path, validator, llm)

    assert result.passed is True
    assert state.build_passed is True
    assert state.heal_attempts == 1
    assert llm.call_count == 1

    # The repair reaches both the state and the file on disk.
    assert state.generated_files["app/main.py"] == "# repaired\n"
    assert (tmp_path / "app" / "main.py").read_text() == "# repaired\n"

    # And it is explained in the ledger.
    heal_entries = [entry for entry in state.ledger if entry.stage == "self-heal"]
    assert len(heal_entries) == 1
    assert "undefined_name" in heal_entries[0].rationale


def test_circuit_breaker_stops_after_the_attempt_limit(tmp_path):
    """A project that never recovers must not loop forever."""
    state = build_state()
    validator = ScriptedValidator([])  # always fails
    llm = CountingRepairLLM()

    result = validate_and_heal(state, tmp_path, validator, llm)

    assert result.passed is False
    assert state.build_passed is False
    assert state.heal_attempts == MAX_HEAL_ATTEMPTS
    assert llm.call_count == MAX_HEAL_ATTEMPTS

    # The validator runs once more than it repairs: the final attempt is checked.
    assert validator.call_count == MAX_HEAL_ATTEMPTS + 1


def test_failure_is_explained_when_the_breaker_trips(tmp_path):
    """Giving up must still tell the user what went wrong."""
    state = build_state()
    validator = ScriptedValidator([])
    llm = CountingRepairLLM()

    validate_and_heal(state, tmp_path, validator, llm)

    assert "undefined_name" in state.error_log
    assert "import" in state.error_log
    assert str(MAX_HEAL_ATTEMPTS) in state.error_log


def test_without_a_model_the_project_is_reported_not_repaired(tmp_path):
    """Validation still runs with no API key; nothing is changed."""
    state = build_state()
    validator = ScriptedValidator([])

    result = validate_and_heal(state, tmp_path, validator, llm=None)

    assert result.passed is False
    assert state.heal_attempts == 0
    assert state.generated_files["app/main.py"] == "# original\n"
    assert validator.call_count == 1


def test_progress_messages_are_reported(tmp_path):
    """The caller can follow what the loop is doing."""
    state = build_state()
    validator = ScriptedValidator(
        [
            ValidationResult.failure(ValidationGate.IMPORT, FAILING_LOG),
            ValidationResult.success(),
        ]
    )
    messages: list[str] = []

    validate_and_heal(
        state, tmp_path, validator, CountingRepairLLM(), on_progress=messages.append
    )

    joined = " ".join(messages)
    assert "Validating" in joined
    assert "Repair attempt 1" in joined
    assert "All validation gates passed." in joined


def test_each_repair_is_checkpointed(tmp_path):
    """State is saved after a repair so a crashed run can be resumed."""
    state = build_state()
    validator = ScriptedValidator(
        [
            ValidationResult.failure(ValidationGate.IMPORT, FAILING_LOG),
            ValidationResult.success(),
        ]
    )

    validate_and_heal(state, tmp_path, validator, CountingRepairLLM())

    restored = load_checkpoint(tmp_path)
    assert restored is not None
    assert restored.heal_attempts == 1
    assert restored.generated_files["app/main.py"] == "# repaired\n"
