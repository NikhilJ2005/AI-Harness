"""Saving and restoring the state of a generation run.

The whole run lives in one ``GenerationState``, so a checkpoint is simply that
object written to disk as JSON. Saving after each healing attempt means an
interrupted run can be resumed instead of started again, and it leaves a record
of what the state looked like when something went wrong.
"""

from pathlib import Path

from vibestack.state import GenerationState

CHECKPOINT_DIRECTORY_NAME = ".vibestack"
CHECKPOINT_FILE_NAME = "checkpoint.json"


def checkpoint_path(project_directory: Path) -> Path:
    """Return the file a project's checkpoint is stored in."""
    return project_directory / CHECKPOINT_DIRECTORY_NAME / CHECKPOINT_FILE_NAME


def save_checkpoint(state: GenerationState, project_directory: Path) -> Path:
    """Write the current state next to the generated project."""
    destination = checkpoint_path(project_directory)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    return destination


def load_checkpoint(project_directory: Path) -> GenerationState | None:
    """Read a saved state, or return None when there is no checkpoint."""
    source = checkpoint_path(project_directory)
    if not source.is_file():
        return None
    return GenerationState.model_validate_json(source.read_text(encoding="utf-8"))
