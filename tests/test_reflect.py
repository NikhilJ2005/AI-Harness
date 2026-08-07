"""Tests for error classification and repair proposals."""

import pytest

from vibestack.stages.reflect import (
    ErrorCategory,
    FilePatch,
    classify_build_error,
    find_referenced_files,
    propose_patch,
    select_files_for_repair,
)
from vibestack.state import GenerationState
from vibestack.spec import Entity, EntityField, FieldType, ProjectSpec
from vibestack.validation import ValidationGate, ValidationResult

# A real traceback, taken from a project with a missing import.
UNDEFINED_NAME_LOG = """
Traceback (most recent call last):
  File "/tmp/project/app/main.py", line 5, in <module>
    from app.models import *
  File "/tmp/project/app/models/post.py", line 23, in Post
    body = Column(Text)
                  ^^^^
NameError: name 'Text' is not defined
"""

MISSING_MODULE_LOG = """
Traceback (most recent call last):
  File "/tmp/project/app/main.py", line 3, in <module>
    import sqlmodel
ModuleNotFoundError: No module named 'sqlmodel'
"""


@pytest.mark.parametrize(
    "logs, expected",
    [
        (UNDEFINED_NAME_LOG, ErrorCategory.UNDEFINED_NAME),
        (MISSING_MODULE_LOG, ErrorCategory.MISSING_DEPENDENCY),
        ("  File 'x.py', line 2\n    def (\nSyntaxError: invalid syntax", ErrorCategory.SYNTAX_ERROR),
        ("ImportError: cannot import name 'Base' from 'app.database'", ErrorCategory.IMPORT_ERROR),
        (
            "sqlalchemy.exc.NoForeignKeysError: Could not determine join condition",
            ErrorCategory.DATABASE_ERROR,
        ),
        ("AttributeError: 'User' object has no attribute 'emial'", ErrorCategory.ATTRIBUTE_ERROR),
        ("TypeError: create_access_token() missing 1 required argument", ErrorCategory.TYPE_ERROR),
        ("E       assert 404 == 200\nFAILED tests/test_health.py", ErrorCategory.TEST_FAILURE),
        ("something nobody has ever seen before", ErrorCategory.UNKNOWN),
    ],
)
def test_classification(logs, expected):
    """Each kind of failure should map to its category."""
    assert classify_build_error(logs) == expected


def test_missing_dependency_wins_over_import_error():
    """ModuleNotFoundError is also an ImportError, so rule order matters."""
    logs = "ImportError\nModuleNotFoundError: No module named 'sqlmodel'"
    assert classify_build_error(logs) == ErrorCategory.MISSING_DEPENDENCY


def test_find_referenced_files_puts_the_innermost_frame_first():
    """The last file in a traceback is usually the one to fix."""
    known_files = ["app/main.py", "app/models/post.py", "app/routers/post.py"]

    found = find_referenced_files(UNDEFINED_NAME_LOG, known_files)

    assert found[0] == "app/models/post.py"
    assert "app/main.py" in found
    assert "app/routers/post.py" not in found


def test_find_referenced_files_ignores_unknown_paths():
    """Files that are not part of the project must never be offered for repair."""
    logs = 'File "/usr/lib/python3.11/site-packages/sqlalchemy/orm.py", line 1'

    assert find_referenced_files(logs, ["app/main.py"]) == []


def _state_with_files(files: dict[str, str]) -> GenerationState:
    """Build a state carrying the given generated files."""
    spec = ProjectSpec(
        project_name="demo",
        description="",
        entities=[
            Entity(name="Note", fields=[EntityField(name="id", type=FieldType.INTEGER)])
        ],
    )
    state = GenerationState(spec=spec)
    state.generated_files.update(files)
    return state


def test_select_files_sends_only_what_the_traceback_mentions():
    """Only the relevant files are sent, which is what keeps repairs cheap."""
    state = _state_with_files(
        {
            "app/main.py": "main",
            "app/models/post.py": "post model",
            "app/routers/comment.py": "unrelated",
        }
    )
    result = ValidationResult.failure(ValidationGate.IMPORT, UNDEFINED_NAME_LOG)

    selected = select_files_for_repair(state, result)

    assert "app/models/post.py" in selected
    assert "app/routers/comment.py" not in selected


def test_select_files_falls_back_to_the_entry_point():
    """With no file named in the log, the entry point is a sensible start."""
    state = _state_with_files({"app/main.py": "main"})
    result = ValidationResult.failure(ValidationGate.BOOT, "something went wrong")

    assert list(select_files_for_repair(state, result)) == ["app/main.py"]


class FakeRepairLLM:
    """Returns a fixed patch and records the prompt it was given."""

    def __init__(self, patch: FilePatch) -> None:
        self._patch = patch
        self.last_user_prompt = ""

    def structured_completion(self, system_prompt, user_prompt, response_model, tier=None):
        self.last_user_prompt = user_prompt
        return self._patch


def test_propose_patch_rejects_a_file_that_does_not_exist():
    """A model naming an unknown file must not be able to create one."""
    state = _state_with_files({"app/main.py": "main"})
    result = ValidationResult.failure(ValidationGate.IMPORT, UNDEFINED_NAME_LOG)
    llm = FakeRepairLLM(
        FilePatch(file_path="app/evil.py", new_content="print()", explanation="nope")
    )

    assert propose_patch(state, result, llm) is None


def test_propose_patch_rejects_empty_content():
    """A patch that empties a file is never useful."""
    state = _state_with_files({"app/main.py": "main"})
    result = ValidationResult.failure(ValidationGate.IMPORT, UNDEFINED_NAME_LOG)
    llm = FakeRepairLLM(
        FilePatch(file_path="app/main.py", new_content="   ", explanation="deleted it")
    )

    assert propose_patch(state, result, llm) is None


def test_propose_patch_includes_the_diagnosis_in_the_prompt():
    """The model is told the category, not left to work it out."""
    state = _state_with_files({"app/models/post.py": "post model"})
    result = ValidationResult.failure(ValidationGate.IMPORT, UNDEFINED_NAME_LOG)
    llm = FakeRepairLLM(
        FilePatch(
            file_path="app/models/post.py",
            new_content="fixed",
            explanation="added the missing import",
        )
    )

    patch = propose_patch(state, result, llm)

    assert patch is not None
    assert "undefined_name" in llm.last_user_prompt
    assert "post model" in llm.last_user_prompt
