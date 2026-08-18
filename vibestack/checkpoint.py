"""Saving and restoring the state of a generation run."""

from pathlib import Path

from vibestack.state import GenerationState

CHECKPOINT_DIRECTORY_NAME = ".vibestack"
CHECKPOINT_FILE_NAME = "checkpoint.json"


def checkpoint_path(project_directory: Path) -> Path:
    return project_directory / CHECKPOINT_DIRECTORY_NAME / CHECKPOINT_FILE_NAME


def save_checkpoint(state: GenerationState, project_directory: Path) -> Path:
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
