"""Writing a finished generation to disk."""

from pathlib import Path

from vibestack.state import GenerationState


def write_workspace(state: GenerationState, output_directory: Path) -> list[Path]:
    """Write every generated file into ``output_directory``.

    Parent directories are created as needed. Returns the paths written, in
    sorted order, so callers can report exactly what was produced.
    """
    written_paths: list[Path] = []

    for relative_path in sorted(state.generated_files):
        content = state.generated_files[relative_path]
        destination = output_directory / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        written_paths.append(destination)

    return written_paths
