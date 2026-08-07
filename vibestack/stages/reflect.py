"""Diagnose a failed build and propose a fix.

Repair happens in two steps, and the split is deliberate.

First the failure is *classified* by a set of ordered rules. This part is
completely deterministic: the same log always produces the same category, it
costs nothing, and it can be unit tested against real tracebacks. The category
then selects specific repair guidance, so the model is told what kind of mistake
it is looking at rather than being asked to work it out from scratch.

Second, only the files the traceback actually mentions are sent to the model,
together with that guidance. Sending the whole project on every attempt would be
the obvious approach and also the expensive one; a traceback already says where
the problem is.
"""

import re
from enum import Enum

from pydantic import BaseModel

from vibestack.llm_protocol import ModelTier, StructuredLLM
from vibestack.state import GenerationState
from vibestack.validation import ValidationResult

# At most this many files are sent to the repair model, cheapest fix first.
MAX_FILES_IN_CONTEXT = 3


class ErrorCategory(str, Enum):
    """The kinds of failure the repair step knows how to handle."""

    MISSING_DEPENDENCY = "missing_dependency"
    SYNTAX_ERROR = "syntax_error"
    UNDEFINED_NAME = "undefined_name"
    IMPORT_ERROR = "import_error"
    ATTRIBUTE_ERROR = "attribute_error"
    DATABASE_ERROR = "database_error"
    VALIDATION_ERROR = "validation_error"
    TYPE_ERROR = "type_error"
    TEST_FAILURE = "test_failure"
    UNKNOWN = "unknown"


# Ordered rules: the first category whose markers appear in the log wins.
# Order matters, so the most specific cases are listed first. A missing module
# raises ModuleNotFoundError, which is also an ImportError, so it must be
# checked before the general import case.
CLASSIFICATION_RULES: list[tuple[ErrorCategory, tuple[str, ...]]] = [
    (ErrorCategory.MISSING_DEPENDENCY, ("ModuleNotFoundError", "No module named")),
    (ErrorCategory.SYNTAX_ERROR, ("SyntaxError", "IndentationError")),
    (ErrorCategory.UNDEFINED_NAME, ("NameError",)),
    (ErrorCategory.IMPORT_ERROR, ("ImportError", "cannot import name")),
    (
        ErrorCategory.DATABASE_ERROR,
        (
            "sqlalchemy.exc",
            "OperationalError",
            "NoForeignKeysError",
            "InvalidRequestError",
            "ArgumentError",
        ),
    ),
    (ErrorCategory.VALIDATION_ERROR, ("ValidationError", "pydantic_core")),
    (ErrorCategory.ATTRIBUTE_ERROR, ("AttributeError",)),
    (ErrorCategory.TYPE_ERROR, ("TypeError",)),
    (ErrorCategory.TEST_FAILURE, ("assert", "AssertionError", "FAILED")),
]


# What to tell the repair model once the category is known.
REPAIR_GUIDANCE: dict[ErrorCategory, str] = {
    ErrorCategory.MISSING_DEPENDENCY: (
        "A module could not be found. Either the import refers to a package that "
        "is not declared in pyproject.toml, or the module path is wrong. Prefer "
        "correcting the import over adding a new dependency."
    ),
    ErrorCategory.SYNTAX_ERROR: (
        "The file is not valid Python. Fix the syntax without changing behaviour."
    ),
    ErrorCategory.UNDEFINED_NAME: (
        "A name is used that was never defined or imported. The usual cause is a "
        "missing entry in the import list at the top of the file."
    ),
    ErrorCategory.IMPORT_ERROR: (
        "An import failed even though the module exists. Check that the imported "
        "name is actually defined in the target module, and watch for circular "
        "imports between models, schemas, and routers."
    ),
    ErrorCategory.ATTRIBUTE_ERROR: (
        "An attribute was accessed that does not exist. Check the class or module "
        "actually defines it, and that the name is spelled consistently."
    ),
    ErrorCategory.DATABASE_ERROR: (
        "SQLAlchemy rejected the model definitions. Common causes are a "
        "relationship whose foreign key is missing, a back_populates that does not "
        "match the attribute on the other side, or a table name used twice."
    ),
    ErrorCategory.VALIDATION_ERROR: (
        "A Pydantic model rejected its input. Check the field types and whether a "
        "field should be optional."
    ),
    ErrorCategory.TYPE_ERROR: (
        "A function was called with the wrong arguments or types. Check the call "
        "against the definition."
    ),
    ErrorCategory.TEST_FAILURE: (
        "The application imports and starts, but a test failed. Correct the "
        "application code so the expected behaviour holds. Do not weaken the test."
    ),
    ErrorCategory.UNKNOWN: (
        "Work out the cause from the log and make the smallest change that fixes it."
    ),
}


REPAIR_SYSTEM_PROMPT = """
You repair a single file in a generated FastAPI project.

Rules:
- Change exactly one file, and return its complete new contents.
- Make the smallest change that fixes the reported error.
- Do not remove features, weaken security, or delete tests to make an error go away.
- Keep the existing style: type hints, docstrings, and clear names.
- file_path must be one of the paths you were shown.
""".strip()


class FilePatch(BaseModel):
    """A proposed replacement for one file."""

    file_path: str
    new_content: str
    explanation: str


def classify_build_error(logs: str) -> ErrorCategory:
    """Work out what kind of failure a log describes.

    Walks the rules in order and returns the first category whose markers appear.
    Being a plain decision list keeps it predictable and easy to test.
    """
    for category, markers in CLASSIFICATION_RULES:
        for marker in markers:
            if marker in logs:
                return category
    return ErrorCategory.UNKNOWN


def find_referenced_files(logs: str, known_files: list[str]) -> list[str]:
    """Return the generated files a traceback mentions, most relevant first.

    Python prints the innermost frame last, so the file named at the end of a
    traceback is usually where the problem is. The list is reversed to put that
    file first.
    """
    quoted_paths = re.findall(r'File "([^"]+)"', logs)
    bare_paths = re.findall(r"([\w/]+\.py)", logs)
    mentioned_paths = quoted_paths + bare_paths

    ordered_matches: list[str] = []
    for mentioned in mentioned_paths:
        normalised = mentioned.replace("\\", "/")
        for known_file in known_files:
            if normalised.endswith(known_file) and known_file not in ordered_matches:
                ordered_matches.append(known_file)

    ordered_matches.reverse()
    return ordered_matches


def build_repair_prompt(
    category: ErrorCategory,
    result: ValidationResult,
    files_to_show: dict[str, str],
) -> str:
    """Assemble the message describing the failure and the relevant files."""
    gate_name = result.failed_gate.value if result.failed_gate else "unknown"

    sections = [
        f"The '{gate_name}' validation gate failed.",
        f"Diagnosis: {category.value}.",
        f"Guidance: {REPAIR_GUIDANCE[category]}",
        "",
        "Error log:",
        result.logs,
        "",
        "Files that may need changing:",
    ]

    for file_path, content in files_to_show.items():
        sections.append(f"\n--- {file_path} ---\n{content}")

    return "\n".join(sections)


def select_files_for_repair(
    state: GenerationState, result: ValidationResult
) -> dict[str, str]:
    """Pick the files to send to the repair model.

    Only the files named in the traceback are sent. If the log names none, the
    application entry point is sent as a starting point.
    """
    known_files = sorted(state.generated_files)
    referenced = find_referenced_files(result.logs, known_files)

    if not referenced and "app/main.py" in state.generated_files:
        referenced = ["app/main.py"]

    chosen = referenced[:MAX_FILES_IN_CONTEXT]
    return {path: state.generated_files[path] for path in chosen}


def propose_patch(
    state: GenerationState,
    result: ValidationResult,
    llm: StructuredLLM,
) -> FilePatch | None:
    """Ask the model for a fix, and return it only if it is usable.

    Returns None when there is nothing to send or the model names a file that
    does not exist, so a bad suggestion can never corrupt the project.
    """
    category = classify_build_error(result.logs)
    files_to_show = select_files_for_repair(state, result)
    if not files_to_show:
        return None

    patch = llm.structured_completion(
        system_prompt=REPAIR_SYSTEM_PROMPT,
        user_prompt=build_repair_prompt(category, result, files_to_show),
        response_model=FilePatch,
        # Repair is the hard reasoning step, so it gets the strongest model.
        tier=ModelTier.PREMIUM,
    )

    if patch.file_path not in state.generated_files:
        return None
    if not patch.new_content.strip():
        return None

    return patch
