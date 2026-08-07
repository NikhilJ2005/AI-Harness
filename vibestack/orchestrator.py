"""The pipeline that turns a prompt into a validated project on disk.

This function reads top to bottom on purpose: it *is* the architecture. Parse the
request, generate the files, prove they work, and hand back a project the user
can run.
"""

from pathlib import Path

from vibestack.agent import GenerationAgent
from vibestack.checkpoint import save_checkpoint
from vibestack.healing import ProgressCallback, validate_and_heal
from vibestack.llm_protocol import StructuredLLM
from vibestack.spec import ProjectSpec
from vibestack.stages.parse import parse_prompt_to_spec
from vibestack.state import GenerationState
from vibestack.validation import Validator
from vibestack.workspace import write_workspace


def generate_from_spec(
    spec: ProjectSpec,
    output_directory: Path,
    validator: Validator | None = None,
    llm: StructuredLLM | None = None,
    on_progress: ProgressCallback | None = None,
) -> GenerationState:
    """Generate a project from a specification, and prove that it works.

    Args:
        spec: What to build.
        output_directory: Where to write the project.
        validator: How to check the result. Skipped entirely when None.
        llm: Used to repair failures. Without one, failures are reported but
            not fixed.
        on_progress: Optional callback for progress messages.
    """
    agent = GenerationAgent()
    state = agent.run(spec)

    write_workspace(state, output_directory)
    save_checkpoint(state, output_directory)

    if validator is not None:
        validate_and_heal(state, output_directory, validator, llm, on_progress)
        save_checkpoint(state, output_directory)

    return state


def run_pipeline(
    prompt: str,
    llm: StructuredLLM,
    output_directory: Path,
    validator: Validator | None = None,
    on_progress: ProgressCallback | None = None,
) -> GenerationState:
    """Turn a natural-language prompt into a validated project.

    Stage 1 uses the language model, because understanding informal prose is what
    models are good at. Generation itself is deterministic. The model returns at
    the end, but only to repair whatever the validation gates caught.
    """
    spec = parse_prompt_to_spec(prompt, llm)
    return generate_from_spec(
        spec,
        output_directory,
        validator=validator,
        llm=llm,
        on_progress=on_progress,
    )
